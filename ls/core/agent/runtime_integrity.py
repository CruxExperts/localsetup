"""Exact installed-environment inventory, separate from artifact authenticity."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import sys

INVENTORY = 'inventory.json'
MAX_FILES = 30000
MAX_BYTES = 1024 * 1024 * 1024


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def snapshot(release: Path, interpreter: Path) -> dict:
    root = release / 'venv'
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Runtime environment must be a regular directory')
    root_info = root.stat()
    if root_info.st_uid != os.getuid() or root_info.st_mode & 0o022:
        raise ValueError('Runtime environment root has unsafe ownership or permissions')
    interpreter = interpreter.resolve(strict=True)
    host = interpreter.stat()
    if not stat.S_ISREG(host.st_mode) or host.st_uid not in {0, os.getuid()} or host.st_mode & 0o022:
        raise ValueError('Host interpreter is not a trusted regular executable')
    links = {'lib64': 'lib', 'bin/python': str(interpreter), 'bin/python3': 'python',
             f'bin/python{sys.version_info.major}.{sys.version_info.minor}': 'python'}
    files = {}
    total = 0
    def fail(error):
        raise error
    for directory, names, filenames in os.walk(root, followlinks=False, onerror=fail):
        for name in sorted([*names, *filenames]):
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            info = path.lstat()
            if len(files) >= MAX_FILES:
                raise ValueError('Installed runtime inventory is too large')
            if info.st_uid != os.getuid():
                raise ValueError('Installed runtime entry is not owned by the current user')
            if stat.S_ISLNK(info.st_mode):
                target = os.readlink(path)
                if relative not in links or target != links[relative]:
                    raise ValueError('Unexpected installed runtime symlink')
                files[relative] = {'kind': 'symlink', 'target': target}
                continue
            mode = stat.S_IMODE(info.st_mode)
            if mode & 0o022:
                raise ValueError('Installed runtime entry is writable by other users')
            if stat.S_ISDIR(info.st_mode):
                files[relative] = {'kind': 'directory', 'mode': mode}
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                total += info.st_size
                if total > MAX_BYTES:
                    raise ValueError('Installed runtime exceeds its byte limit')
                files[relative] = {'kind': 'file', 'mode': mode, 'sha256': _hash(path)}
            else:
                raise ValueError('Installed runtime contains a special or hardlinked file')
    return {'schema_version': 1, 'python': str(interpreter), 'python_sha256': _hash(interpreter), 'root_mode': stat.S_IMODE(root_info.st_mode), 'files': files}


def encode(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


def seal(release: Path) -> str:
    target = release / INVENTORY
    data = encode(snapshot(release, Path(sys.executable)))
    with target.open('xb') as stream:
        os.chmod(target, 0o600)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(data).hexdigest()


def verify(release: Path, expected: str) -> None:
    target = release / INVENTORY
    if target.is_symlink() or not target.is_file() or target.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('Missing or invalid installed runtime inventory')
    data = target.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError('Installed runtime inventory digest differs from selection')
    recorded = json.loads(data)
    if not isinstance(recorded, dict) or not isinstance(recorded.get('python'), str):
        raise ValueError('Malformed installed runtime inventory')
    if encode(snapshot(release, Path(recorded['python']))) != data:
        raise ValueError('Installed runtime changed after qualification')
