"""Explicit file-grant projections for disposable process workspaces."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
import time
import uuid

from .file_broker import FileBroker
from .file_grants import FileGrant
from .runtime_install import _write_json
from .runtime_lock import _directory, runtime_use
from .sandbox import ProcessGrant


@dataclass(frozen=True)
class Snapshot:
    staging: Path
    manifest: Path
    authority: FileGrant
    disclose_output: bool

    def process(self, command: tuple[str, ...], *, expires: float) -> ProcessGrant:
        if expires > self.authority.expires:
            raise PermissionError('Process deadline cannot exceed source grant deadline')
        return ProcessGrant(self.authority.task, self.authority.session, self.staging,
                            command, expires, self.disclose_output, self.authority.revoked)


def create(broker: FileBroker, root: Path, names: tuple[str, ...], *, task: str, session: str,
           for_provider: bool = False) -> Snapshot:
    """Retain incomplete projections on failure; never derive grants from records."""
    if type(for_provider) is not bool or not isinstance(names, tuple) or not names or len(names) > 30000:
        raise ValueError('Snapshot requires an explicit nonempty immutable file inventory')
    if any(not isinstance(n, str) for n in names) or len(set(names)) != len(names):
        raise ValueError('Snapshot inventory contains invalid or duplicate names')
    selected_names = set(names)
    entries = set()
    for name in names:
        parts = broker.grant.check(task, session, 'read', name, provider=for_provider)
        if len(name.encode()) > 4096 or len(parts) > 128 or 'AGENTS.md' in parts:
            raise PermissionError('Snapshot path is oversized or protected context')
        if any('/'.join(parts[:i]) in selected_names for i in range(1, len(parts))):
            raise ValueError('Snapshot inventory conflicts between files and directories')
        entries.update('/'.join(parts[:i]) for i in range(1, len(parts)+1))
        if len(entries) > 30000:
            raise ValueError('Snapshot inventory exceeds 30000 files and directories')
    root = root.absolute()
    for boundary in (broker.grant.root.resolve(), broker.lease_root.resolve()):
        if root.resolve().is_relative_to(boundary) or boundary.is_relative_to(root.resolve()):
            raise ValueError('Snapshot storage must be separate from workspace and target leases')
    fd = _directory(root)
    try:
        if stat.S_IMODE(os.fstat(fd).st_mode) & 0o077:
            raise ValueError('Snapshot storage must be private')
        identifier = uuid.uuid4().hex
        os.mkdir(identifier, mode=0o700, dir_fd=fd)
        os.fsync(fd)
    finally:
        os.close(fd)
    container = root / identifier
    staging, manifest = container / 'files', container / 'manifest.json'
    staging.mkdir(mode=0o700)
    base = {'schema_version': 1, 'task': task, 'session': session}
    _write_json(manifest, {**base, 'status': 'incomplete'})
    files, size = {}, 0
    # One shared target lease blocks cooperating mutations across all reads.
    with runtime_use(broker.lease_root, timeout=max(0, broker.grant.expires-time.monotonic())):
        for name in sorted(names):
            data, source_mode = broker.read_entry(task, session, name, for_provider=for_provider)
            size += len(data)
            if size > 256 * 1024 * 1024:
                raise ValueError('Snapshot input exceeds 256 MiB')
            target = staging / name
            directory = staging
            for part in Path(name).parts[:-1]:
                directory /= part
                directory.mkdir(mode=0o700, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(data)
                os.fchmod(stream.fileno(), 0o600 | (source_mode & 0o100))
                stream.flush()
                os.fsync(stream.fileno())
            files[name] = {'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data), 'source_mode': source_mode}
        for directory, _, _ in os.walk(staging, topdown=False):
            directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        for name in names:
            broker.grant.check(task, session, 'read', name, provider=for_provider)
        _write_json(manifest, {**base, 'status': 'prepared', 'files': files})
    return Snapshot(staging, manifest, broker.grant, for_provider)
