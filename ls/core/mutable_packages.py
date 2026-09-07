"""Content baselines for isolated, mutable agent package copies.

Callers own receipt storage, transactions, locks and quiescing native writers.
These checks detect drift; they do not create a sandbox or authorize overwrites.
"""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Mapping

from .adapter_markers import is_safe_adapter_package_name


MAX_ENTRIES = 10000
MAX_BYTES = 512 * 1024 * 1024


class MutablePackageError(ValueError):
    """A copy cannot be safely accepted or changed without preservation review."""


def _frame(digest, value: bytes) -> None:
    digest.update(len(value).to_bytes(8, 'big'))
    digest.update(value)


def _bounded_names(fd: int) -> list[str]:
    names = []
    with os.scandir(fd) as entries:
        for entry in entries:
            if len(names) >= MAX_ENTRIES:
                raise MutablePackageError('Mutable package exceeds the supported entry limit')
            names.append(entry.name)
    return sorted(names)


def package_fingerprint(path: Path) -> str:
    """Hash all names, modes and bytes, requiring independent regular files.

    Includes package metadata and empty directories. Never follows resource links.
    Rejects concurrent changes observed during scanning, without claiming to lock
    an external writer that does not cooperate with the caller's transaction.
    """
    digest = hashlib.sha256()
    count = total_bytes = 0
    fields = ('st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns')

    def identity(info):
        return tuple(getattr(info, key) for key in fields)

    def visit(parent: int | None, name, relative: str) -> None:
        nonlocal count, total_bytes
        count += 1
        if count > MAX_ENTRIES:
            raise MutablePackageError('Mutable package exceeds the supported entry limit')
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        directory = stat.S_ISDIR(before.st_mode)
        if not directory and not (stat.S_ISREG(before.st_mode) and before.st_nlink == 1):
            raise MutablePackageError('Mutable packages require directories and independent regular files')
        if not relative and not directory:
            raise MutablePackageError('Mutable package root must be a regular directory')
        flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW
        fd = os.open(name, flags | (os.O_DIRECTORY if directory else 0), dir_fd=parent)
        try:
            if identity(os.fstat(fd)) != identity(before):
                raise MutablePackageError('Mutable package changed during inspection')
            _frame(digest, relative.encode('utf-8'))
            _frame(digest, str(stat.S_IMODE(before.st_mode)).encode('ascii'))
            _frame(digest, b'directory' if directory else b'file')
            if directory:
                names = _bounded_names(fd)
                for child in names:
                    visit(fd, child, f'{relative}/{child}')
                if names != _bounded_names(fd):
                    raise MutablePackageError('Mutable package changed during inspection')
            else:
                content = hashlib.sha256()
                while chunk := os.read(fd, 1024 * 1024):
                    total_bytes += len(chunk)
                    if total_bytes > MAX_BYTES:
                        raise MutablePackageError('Mutable package exceeds the supported byte limit')
                    content.update(chunk)
                _frame(digest, content.digest())
            if (identity(os.fstat(fd)) != identity(before)
                    or identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != identity(before)):
                raise MutablePackageError('Mutable package changed during inspection')
        finally:
            os.close(fd)

    try:
        visit(None, path, '')
    except (OSError, UnicodeError, RecursionError) as exc:
        raise MutablePackageError('Mutable package is missing, unsafe or unreadable; preserve it for review') from exc
    return digest.hexdigest()


def capture_baselines(adapter: Path, names: list[str]) -> dict[str, str]:
    """Return receipt data after copying; the caller stores it outside packages."""
    if not isinstance(names, list) or any(not isinstance(n, str) or not is_safe_adapter_package_name(n) for n in names):
        raise MutablePackageError('Invalid mutable package selection')
    if len(names) != len(set(names)):
        raise MutablePackageError('Duplicate mutable package selection')
    if adapter.is_symlink() or not adapter.is_dir():
        raise MutablePackageError('Mutable adapter must be a regular directory')
    return {name: package_fingerprint(adapter / name) for name in sorted(names)}


def require_unchanged(adapter: Path, baseline: Mapping[str, str]) -> None:
    """Fail closed before replacing/removing any recorded package, including deletions."""
    if not isinstance(baseline, Mapping) or any(
            not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value)
            for value in baseline.values()):
        raise MutablePackageError('Invalid mutable package baseline')
    current = capture_baselines(adapter, list(baseline))
    if current != dict(baseline):
        raise MutablePackageError('Mutable package has local changes; preserve them before replacement or removal')
