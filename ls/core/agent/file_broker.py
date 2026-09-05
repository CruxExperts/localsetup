"""Anchored regular-file operations under explicit task authority and leases."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import stat
import time
import uuid

from .file_grants import FileGrant
from .runtime_lock import runtime_use

MAX_FILE = 8 * 1024 * 1024


@contextmanager
def parent(root: Path, parts: tuple[str, ...]):
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in (*root.parts[1:], *parts[:-1]):
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        yield fd, parts[-1]
    finally:
        os.close(fd)


def _regular(info):
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or info.st_mode & 0o7000:
        raise PermissionError('Broker requires an owned regular single-link file without special modes')


class FileBroker:
    def __init__(self, grant: FileGrant, lease_root: Path):
        if lease_root.resolve().is_relative_to(grant.root.resolve()) or grant.root.resolve().is_relative_to(lease_root.resolve()):
            raise ValueError('Broker lease state and granted tree must be separate')
        self.grant, self.lease_root = grant, lease_root

    @contextmanager
    def _target(self, task, session, operation, name, provider=False):
        parts = self.grant.check(task, session, operation, name, provider=provider)
        with runtime_use(self.lease_root, exclusive=operation == 'write', timeout=max(0, self.grant.expires-time.monotonic())):
            self.grant.check(task, session, operation, name, provider=provider)
            with parent(self.grant.root, parts) as target:
                yield target

    def read(self, task: str, session: str, name: str, *, for_provider: bool = False) -> bytes:
        with self._target(task, session, 'read', name, for_provider) as (directory, leaf):
            fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            try:
                before = os.fstat(fd)
                _regular(before)
                data = bytearray()
                while chunk := os.read(fd, min(65536, MAX_FILE + 1 - len(data))):
                    data.extend(chunk)
                    if len(data) > MAX_FILE:
                        raise ValueError('Broker file exceeds 8 MiB')
                after = os.fstat(fd)
                if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                    raise PermissionError('Broker file changed during read')
                self.grant.check(task, session, 'read', name, provider=for_provider)
                return bytes(data)
            finally:
                os.close(fd)

    def write(self, task: str, session: str, name: str, data: bytes) -> None:
        if not isinstance(data, bytes) or len(data) > MAX_FILE:
            raise ValueError('Broker replacement must be bytes within 8 MiB')
        with self._target(task, session, 'write', name) as (directory, leaf):
            original, attributes = None, {}
            try:
                source = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            except FileNotFoundError:
                pass
            else:
                try:
                    original = os.fstat(source)
                    _regular(original)
                    if hasattr(os, 'listxattr'):
                        attributes = {key: os.getxattr(source, key) for key in os.listxattr(source)}
                finally:
                    os.close(source)
            temporary = '.lscli-write-' + uuid.uuid4().hex
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(data)
                    stream.flush()
                    if original is not None:
                        os.fchmod(stream.fileno(), stat.S_IMODE(original.st_mode))
                        os.fchown(stream.fileno(), original.st_uid, original.st_gid)
                    for key, value in attributes.items():
                        os.setxattr(stream.fileno(), key, value)
                    os.fsync(stream.fileno())
                self.grant.check(task, session, 'write', name)
                try:
                    current = os.stat(leaf, dir_fd=directory, follow_symlinks=False)
                except FileNotFoundError:
                    current = None
                if (current is None) != (original is None) or (current is not None and (current.st_dev, current.st_ino, current.st_mtime_ns, current.st_ctime_ns) != (original.st_dev, original.st_ino, original.st_mtime_ns, original.st_ctime_ns)):
                    raise PermissionError('Broker target changed during replacement')
                os.replace(temporary, leaf, src_dir_fd=directory, dst_dir_fd=directory)
                os.fsync(directory)
            finally:
                try:
                    os.unlink(temporary, dir_fd=directory)
                except FileNotFoundError:
                    pass
