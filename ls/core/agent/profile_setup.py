"""Explicit create-only provider configuration with noncreating plans."""
import hashlib
import json
import os
from pathlib import Path
import stat
import uuid

from .profile_inventory import validate
from .profiles import document, parse, wire


def _content(source: Path) -> tuple[bytes, int]:
    values = document(source)
    validate(values)
    if not values:
        raise ValueError('Setup requires at least one explicit profile')
    data = json.dumps({'schema_version': 1, 'profiles': {
        name: wire(parse(value)) for name, value in sorted(values.items())
    }}, sort_keys=True, ensure_ascii=True, indent=2).encode() + b'\n'
    if len(data) > 1024 * 1024:
        raise ValueError('Canonical profiles exceed 1 MiB')
    return data, len(values)


def _target(path: Path) -> Path:
    path = path.absolute()
    if '..' in path.parts or len(path.parts) > 128:
        raise ValueError('Configuration target must be canonical and bounded')
    return path


def _parent(target: Path, *, create: bool) -> int | None:
    """Anchor each component; allow a root-owned sticky temporary ancestor."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(target.anchor, flags)
    try:
        for part in target.parts[1:-1]:
            try:
                child = os.open(part, flags, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    os.close(fd)
                    return None
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            sticky_system = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
            if info.st_uid not in {0, os.getuid()} or (info.st_mode & 0o022 and not sticky_system):
                raise ValueError('Configuration ancestor has unsafe ownership or permissions')
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise ValueError('Configuration parent must be private to its owner')
        return fd
    except BaseException:
        os.close(fd)
        raise


def _absent(fd: int, name: str) -> None:
    try:
        os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise FileExistsError('Configuration target exists; preserve and review it separately')


def plan(source: Path, target: Path) -> dict:
    data, count = _content(source)
    target = _target(target)
    fd = _parent(target, create=False)
    if fd is not None:
        try:
            _absent(fd, target.name)
        finally:
            os.close(fd)
    return {'schema_version': 1, 'operation': 'create_profiles', 'target': str(target),
            'sha256': hashlib.sha256(data).hexdigest(), 'profile_count': count,
            'expected_target': 'absent'}


def apply(source: Path, target: Path, expected_sha256: str) -> dict:
    data, count = _content(source)
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected_sha256:
        raise ValueError('Profile input changed or expected plan digest does not match')
    target = _target(target)
    # Preflight never allocates directories for a known conflict.
    specification = plan(source, target)
    if specification['sha256'] != digest:
        raise ValueError('Profile input changed during preflight')
    fd = _parent(target, create=True)
    temporary = '.profiles-' + uuid.uuid4().hex
    created = False
    try:
        _absent(fd, target.name)
        stream_fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        created = True
        with os.fdopen(stream_fd, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, target.name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
        os.unlink(temporary, dir_fd=fd)
        created = False
        os.fsync(fd)
        return dict(specification, status='created', profile_count=count)
    finally:
        try:
            if created:
                os.unlink(temporary, dir_fd=fd)
        finally:
            os.close(fd)
