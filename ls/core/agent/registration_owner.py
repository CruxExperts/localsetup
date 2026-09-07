"""Receipt-backed fresh command publication; uncertain writes are not replayed."""
import hashlib
import json
import os
from pathlib import Path
import stat
import uuid

from ..branding import CLI_COMMAND
from .profile_setup import _absent, _parent, _target
from .registration_plan import launcher, plan as fresh_plan
from .runtime_install import DIGEST, selected
from .runtime_lock import runtime_use

RECEIPT = '.lscli-registration.json'
PENDING = '.lscli-registration.pending.json'
LIMIT = 64 * 1024


def encode(value: dict) -> bytes:
    data = (json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':')) + '\n').encode()
    if len(data) > LIMIT:
        raise ValueError('Registration metadata exceeds 64 KiB')
    return data


def _read(fd: int, name: str, *, executable: bool = False) -> bytes | None:
    try:
        child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(child)
        mode = 0o700 if executable else 0o600
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != mode or info.st_size > LIMIT:
            raise ValueError('Registration file has unsafe type, ownership, mode or size')
        with os.fdopen(child, 'rb', closefd=False) as stream:
            data = stream.read(LIMIT + 1)
        if len(data) > LIMIT:
            raise ValueError('Registration file exceeds 64 KiB')
        return data
    finally:
        os.close(child)


def _publish(fd: int, name: str, data: bytes, mode: int) -> None:
    temporary = '.lscli-write-' + uuid.uuid4().hex
    child = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=fd)
    try:
        with os.fdopen(child, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
    finally:
        os.unlink(temporary, dir_fd=fd)
    os.fsync(fd)


def plan(root: Path, bin_dir: Path, *, path_env: str | None = None) -> dict:
    result = fresh_plan(root, bin_dir, path_env=path_env)
    fd = _parent(Path(result['target']), create=False)
    if fd is not None:
        try:
            _absent(fd, RECEIPT)
            _absent(fd, PENDING)
        finally:
            os.close(fd)
    result['plan_sha256'] = hashlib.sha256(encode(result)).hexdigest()
    return result


def apply(root: Path, bin_dir: Path, expected_sha256: str, *, path_env: str | None = None) -> dict:
    specification = plan(root, bin_dir, path_env=path_env)
    if specification['plan_sha256'] != expected_sha256 or not specification['path']['ready']:
        raise ValueError('Registration plan changed or bin directory is not effective on PATH')
    root = Path(specification['runtime_root'])
    target = Path(specification['target'])
    with selected(root, timeout=5, create=False) as release:
        if release.name != specification['release']:
            raise ValueError('Runtime selection changed since registration planning')
        parent = _parent(target, create=True)
        try:
            with runtime_use(target.parent, exclusive=True, timeout=5):
                current = plan(root, target.parent, path_env=path_env)
                if current != specification:
                    raise ValueError('Registration inputs changed before publication')
                for name in (CLI_COMMAND, RECEIPT, PENDING):
                    _absent(parent, name)
                record = {'schema_version': 1, 'specification': specification}
                _publish(parent, PENDING, encode(record), 0o600)
                _publish(parent, CLI_COMMAND, specification['launcher'].encode(), 0o700)
                _publish(parent, RECEIPT, encode(record), 0o600)
                os.unlink(PENDING, dir_fd=parent)
                os.fsync(parent)
        finally:
            os.close(parent)
    return {'schema_version': 1, 'status': 'registered', 'target': str(target), 'release': release.name}


def _record(raw: bytes, target: Path) -> dict:
    record = json.loads(raw)
    if not isinstance(record, dict) or set(record) != {'schema_version', 'specification'} or type(record['schema_version']) is not int or record['schema_version'] != 1:
        raise ValueError('Invalid registration receipt')
    spec = record['specification']
    if not isinstance(spec, dict) or set(spec) != {'schema_version','operation','command','target','runtime_root','release','expected_target','launcher_sha256','launcher','path','plan_sha256'}:
        raise ValueError('Invalid registration specification')
    if spec['target'] != str(target) or spec['command'] != CLI_COMMAND or spec['operation'] != 'register_command' or spec['expected_target'] != 'absent' or type(spec['schema_version']) is not int or spec['schema_version'] != 1:
        raise ValueError('Registration receipt identity mismatch')
    if not isinstance(spec['runtime_root'], str) or spec['path'] != {'on_path': True, 'ready': True, 'reason': None} or any(type(spec['path'][key]) is not bool for key in ('on_path', 'ready')):
        raise ValueError('Invalid registration path specification')
    root = Path(spec['runtime_root'])
    if str(_target(root)) != str(root) or target.is_relative_to(root) or not isinstance(spec['release'], str) or not DIGEST.fullmatch(spec['release']):
        raise ValueError('Invalid registered runtime identity')
    content = launcher(root, spec['release'])
    if spec['launcher'] != content.decode() or spec['launcher_sha256'] != hashlib.sha256(content).hexdigest():
        raise ValueError('Registration launcher does not match its receipt')
    body = dict(spec)
    digest = body.pop('plan_sha256')
    if digest != hashlib.sha256(encode(body)).hexdigest():
        raise ValueError('Registration plan digest mismatch')
    return spec


def status(bin_dir: Path) -> dict:
    target = _target(bin_dir / CLI_COMMAND)
    fd = _parent(target, create=False)
    if fd is None:
        return {'status': 'missing'}
    try:
        with runtime_use(target.parent, timeout=5, create=False):
            if _read(fd, PENDING) is not None:
                return {'status': 'incomplete'}
            raw = _read(fd, RECEIPT)
            if raw is None:
                return {'status': 'unmanaged' if _read(fd, CLI_COMMAND, executable=True) is not None else 'missing'}
            spec = _record(raw, target)
            if _read(fd, CLI_COMMAND, executable=True) != spec['launcher'].encode():
                return {'status': 'modified'}
    except FileNotFoundError:
        return {'status': 'coordination_unavailable'}
    finally:
        os.close(fd)
    with selected(Path(spec['runtime_root']), timeout=5, create=False) as release:
        return {'status': 'registered' if release.name == spec['release'] else 'stale', 'release': spec['release']}
