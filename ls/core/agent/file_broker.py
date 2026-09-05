"""Anchored regular-file operations under explicit task authority and leases."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
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
        return self.read_entry(task, session, name, for_provider=for_provider)[0]

    def read_entry(self, task: str, session: str, name: str, *, for_provider: bool = False) -> tuple[bytes, int]:
        """Read coherent bytes and source mode under the same anchored descriptor."""
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
                return bytes(data), stat.S_IMODE(before.st_mode)
            finally:
                os.close(fd)

    def write(self, task: str, session: str, name: str, data: bytes) -> None:
        self._write(task, session, name, data)

    def write_recorded(self, task: str, session: str, name: str, data: bytes, *, expected_before: str | None, journal, checkpoint: str | None = None) -> str:
        from .file_recovery import journal_binding
        journal_binding(self, journal, task, session)
        self.grant.check(task, session, 'read', name)
        if expected_before is not None and (not isinstance(expected_before, str) or len(expected_before) != 64 or any(c not in '0123456789abcdef' for c in expected_before)):
            raise ValueError('Expected file precondition must be SHA-256 or absence')
        return self._write(task, session, name, data, journal=journal, expected_before=expected_before, checkpoint=checkpoint)

    def _write(self, task, session, name, data, *, journal=None, expected_before=None, checkpoint=None):
        if not isinstance(data, bytes) or len(data) > MAX_FILE:
            raise ValueError('Broker replacement must be bytes within 8 MiB')
        recorded_root = None
        if journal is not None:
            from .file_recovery import root_digest
            recorded_root = root_digest(self.grant.root)
        with self._target(task, session, 'write', name) as (directory, leaf):
            original, attributes, before_digest, operation = None, {}, None, None
            before_properties = None
            try:
                source = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            except FileNotFoundError:
                pass
            else:
                try:
                    original = os.fstat(source)
                    _regular(original)
                    if journal is not None:
                        before_digest = digest_descriptor(source, original)
                    if hasattr(os, 'listxattr'):
                        attributes = {key: os.getxattr(source, key) for key in os.listxattr(source)}
                    if journal is not None:
                        before_properties = properties_digest(source, original, attributes)
                finally:
                    os.close(source)
            if journal is not None and before_digest != expected_before:
                raise PermissionError('File content differs from the expected precondition')
            temporary = '.lscli-write-' + uuid.uuid4().hex
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(data)
                    stream.flush()
                    if original is not None:
                        os.fchmod(stream.fileno(), stat.S_IMODE(original.st_mode))
                        os.fchown(stream.fileno(), original.st_uid, original.st_gid)
                    if original is not None and hasattr(os, 'listxattr'):
                        for key in os.listxattr(stream.fileno()):
                            if key not in attributes:
                                os.removexattr(stream.fileno(), key)
                    for key, value in attributes.items():
                        os.setxattr(stream.fileno(), key, value)
                    os.fsync(stream.fileno())
                    after_properties = properties_digest(stream.fileno()) if journal is not None else None
                def check_target():
                    self.grant.check(task, session, 'write', name)
                    if journal is not None and root_digest(self.grant.root) != recorded_root:
                        raise PermissionError('Workspace identity changed during replacement')
                    with parent(self.grant.root, tuple(Path(name).parts)) as (current_directory, _):
                        old_parent, new_parent = os.fstat(directory), os.fstat(current_directory)
                        if (old_parent.st_dev, old_parent.st_ino) != (new_parent.st_dev, new_parent.st_ino):
                            raise PermissionError('Broker parent changed during replacement')
                    try:
                        current = os.stat(leaf, dir_fd=directory, follow_symlinks=False)
                    except FileNotFoundError:
                        current = None
                    if (current is None) != (original is None) or (current is not None and (current.st_dev, current.st_ino, current.st_mtime_ns, current.st_ctime_ns) != (original.st_dev, original.st_ino, original.st_mtime_ns, original.st_ctime_ns)):
                        raise PermissionError('Broker target changed during replacement')
                check_target()
                if journal is not None:
                    self.grant.check(task, session, 'read', name)
                    operation = journal.begin('file_replace', {'path': name, 'before': before_digest,
                        'after': hashlib.sha256(data).hexdigest(), 'root_sha256': recorded_root,
                        'before_properties': before_properties, 'after_properties': after_properties},
                        checkpoint=checkpoint, timeout=max(0, self.grant.expires-time.monotonic()))
                    check_target()
                os.replace(temporary, leaf, src_dir_fd=directory, dst_dir_fd=directory)
                os.fsync(directory)
                if journal is not None:
                    journal.finish(operation, 'applied', evidence_sha256=hashlib.sha256(data).hexdigest(),
                                   timeout=max(0, self.grant.expires-time.monotonic()))
                return operation
            finally:
                try:
                    os.unlink(temporary, dir_fd=directory)
                except FileNotFoundError:
                    pass


def digest_descriptor(fd, before) -> str:
    """Hash a bounded regular descriptor and reject observed content changes."""
    digest, size = hashlib.sha256(), 0
    while chunk := os.read(fd, 65536):
        size += len(chunk)
        if size > MAX_FILE:
            raise ValueError('Recorded file precondition exceeds 8 MiB')
        digest.update(chunk)
    after = os.fstat(fd)
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise PermissionError('File changed while checking its precondition')
    return digest.hexdigest()


def properties_digest(fd, info=None, attributes=None) -> str:
    info = info or os.fstat(fd)
    if attributes is None:
        attributes = {key: os.getxattr(fd, key) for key in os.listxattr(fd)} if hasattr(os, 'listxattr') else {}
    value = {'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid,
             'xattrs': {key: hashlib.sha256(data).hexdigest() for key, data in attributes.items()}}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
