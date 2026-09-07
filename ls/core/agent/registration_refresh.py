"""Explicit owned refresh and reconciliation of known registration write states."""
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import uuid

from ..branding import CLI_COMMAND
from .profile_setup import _absent, _parent, _target
from . import registration_owner as owner
from .registration_plan import specification
from .runtime_install import selected
from .runtime_lock import runtime_use


def _digest(value: bytes | None) -> str | None:
    return None if value is None else hashlib.sha256(value).hexdigest()


def _sealed(body: dict) -> dict:
    return {**body, 'plan_sha256': _digest(owner.encode(body))}


def _open(bin_dir: Path) -> tuple[Path, int]:
    target = _target(bin_dir / CLI_COMMAND)
    fd = _parent(target, create=False)
    if fd is None:
        raise ValueError('Registration directory is missing')
    return target, fd


def _receipt(raw: bytes | None, target: Path) -> dict:
    if raw is None:
        raise ValueError('Registration receipt is missing')
    spec = owner._record(raw, target)
    if raw != owner.encode({'schema_version': 1, 'specification': spec}):
        raise ValueError('Registration receipt bytes were modified')
    return spec


def _new(root: Path, target: Path, path_env: str | None) -> dict:
    spec = _sealed(specification(root, target, path_env=path_env))
    if not spec['path']['ready']:
        raise ValueError('Registration directory is not effective on PATH')
    return {'schema_version': 1, 'specification': spec}


def _snapshot(fd: int) -> dict:
    return {name: _digest(owner._read(fd, name, executable=name == CLI_COMMAND))
            for name in (owner.PENDING, owner.RECEIPT, CLI_COMMAND)}


def plan(bin_dir: Path, *, path_env: str | None = None, _locked: bool = False) -> dict:
    target, fd = _open(bin_dir)
    try:
        with nullcontext() if _locked else runtime_use(target.parent, timeout=5, create=False):
            _absent(fd, owner.PENDING)
            raw = owner._read(fd, owner.RECEIPT)
            before = _receipt(raw, target)
            if owner._read(fd, CLI_COMMAND, executable=True) != before['launcher'].encode():
                raise ValueError('Registered command was modified')
            snapshot = _snapshot(fd)
    finally:
        os.close(fd)
    after = _new(Path(before['runtime_root']), target, path_env)
    if before == after['specification']:
        raise ValueError('Registration already matches the selected release')
    return _sealed({'schema_version': 1, 'operation': 'refresh_registration',
                    'target': str(target), 'before': json.loads(raw), 'after': after,
                    'observed': snapshot})


def _replace(fd: int, name: str, data: bytes, expected: bytes | None, mode: int) -> None:
    """Replace only a validated known regular file; absent targets use no-replace."""
    if owner._read(fd, name, executable=mode == 0o700) != expected:
        raise ValueError('Registration target changed before replacement')
    if expected is None:
        owner._publish(fd, name, data, mode)
        return
    temporary = '.lscli-refresh-' + uuid.uuid4().hex
    owner._publish(fd, temporary, data, mode)
    try:
        if owner._read(fd, name, executable=mode == 0o700) != expected:
            raise ValueError('Registration target changed before replacement')
        os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=fd)
        except FileNotFoundError:
            pass


def _finish(fd: int, after: dict) -> None:
    for name, data, mode in ((CLI_COMMAND, after['specification']['launcher'].encode(), 0o700),
                             (owner.RECEIPT, owner.encode(after), 0o600)):
        current = owner._read(fd, name, executable=mode == 0o700)
        if current != data:
            _replace(fd, name, data, current, mode)
    os.unlink(owner.PENDING, dir_fd=fd)
    os.fsync(fd)


def apply(bin_dir: Path, expected_sha256: str, *, path_env: str | None = None) -> dict:
    planned = plan(bin_dir, path_env=path_env)
    if planned['plan_sha256'] != expected_sha256:
        raise ValueError('Refresh plan changed')
    target = Path(planned['target'])
    spec = planned['after']['specification']
    with selected(Path(spec['runtime_root']), timeout=5, create=False) as release:
        if release.name != spec['release']:
            raise ValueError('Runtime selection changed')
        _, fd = _open(bin_dir)
        try:
            with runtime_use(target.parent, exclusive=True, timeout=5):
                if plan(bin_dir, path_env=path_env, _locked=True) != planned:
                    raise ValueError('Refresh observations changed')
                previous = owner.encode(planned['before'])
                backup = '.lscli-registration.previous-' + _digest(previous) + '.json'
                existing = owner._read(fd, backup)
                if existing is None:
                    owner._publish(fd, backup, previous, 0o600)
                elif existing != previous:
                    raise ValueError('Previous receipt backup conflicts')
                pending = {'schema_version': 1, 'operation': 'refresh_registration',
                           'before': planned['before'], 'after': planned['after']}
                owner._publish(fd, owner.PENDING, owner.encode(pending), 0o600)
                _finish(fd, planned['after'])
        finally:
            os.close(fd)
    return {'schema_version': 1, 'status': 'registered', 'release': spec['release']}


def recovery_plan(bin_dir: Path, *, path_env: str | None = None, _locked: bool = False) -> dict:
    target, fd = _open(bin_dir)
    try:
        with nullcontext() if _locked else runtime_use(target.parent, timeout=5, create=False):
            raw = owner._read(fd, owner.PENDING)
            if raw is None:
                raise ValueError('No pending registration intent')
            pending = json.loads(raw)
            if not isinstance(pending, dict):
                raise ValueError('Invalid pending registration intent')
            if set(pending) == {'schema_version', 'specification'}:
                after = pending
                before = None
            elif set(pending) == {'schema_version', 'operation', 'before', 'after'} and type(pending['schema_version']) is int and pending['schema_version'] == 1 and pending['operation'] == 'refresh_registration':
                before, after = pending['before'], pending['after']
                _receipt(owner.encode(before), target)
            else:
                raise ValueError('Invalid pending registration intent')
            spec = _receipt(owner.encode(after), target)
            if before is not None and before['specification']['runtime_root'] != spec['runtime_root']:
                raise ValueError('Pending refresh changes runtime ownership')
            command = owner._read(fd, CLI_COMMAND, executable=True)
            receipt = owner._read(fd, owner.RECEIPT)
            old_command = None if before is None else before['specification']['launcher'].encode()
            old_receipt = None if before is None else owner.encode(before)
            if command not in (old_command, spec['launcher'].encode()) or receipt not in (old_receipt, owner.encode(after)):
                raise ValueError('Pending publication contains unknown edits')
            snapshot = _snapshot(fd)
    finally:
        os.close(fd)
    if _new(Path(spec['runtime_root']), target, path_env) != after:
        raise ValueError('Pending release is no longer selected or qualified')
    return _sealed({'schema_version': 1, 'operation': 'finish_registration',
                    'target': str(target), 'after': after, 'observed': snapshot})


def recover(bin_dir: Path, expected_sha256: str, *, path_env: str | None = None) -> dict:
    planned = recovery_plan(bin_dir, path_env=path_env)
    if planned['plan_sha256'] != expected_sha256:
        raise ValueError('Recovery observations changed')
    spec = planned['after']['specification']
    with selected(Path(spec['runtime_root']), timeout=5, create=False) as release:
        if release.name != spec['release']:
            raise ValueError('Runtime selection changed')
        target, fd = _open(bin_dir)
        try:
            with runtime_use(target.parent, exclusive=True, timeout=5):
                if recovery_plan(bin_dir, path_env=path_env, _locked=True) != planned:
                    raise ValueError('Recovery observations changed before application')
                _finish(fd, planned['after'])
        finally:
            os.close(fd)
    return {'schema_version': 1, 'status': 'registered', 'release': spec['release']}
