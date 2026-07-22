"""Validate portable archive member names, types, and parent structure."""

from __future__ import annotations

import os
import re
import stat
import tarfile
from pathlib import Path

_ARCHIVE_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

MAX_SNAPSHOT_ARCHIVE_MEMBERS = 100_000
MAX_SNAPSHOT_MANIFEST_BYTES = 16 * 1024

_ARCHIVE_WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")


def read_snapshot_manifest_bytes(
    path: Path,
    *,
    error_type: type[Exception],
) -> bytes:
    """Read a small sidecar through a descriptor whose identity stays bound."""
    try:
        observed = os.lstat(path)
    except OSError as exc:
        raise error_type("snapshot sidecar cannot be inspected") from exc
    if not stat.S_ISREG(observed.st_mode):
        raise error_type("snapshot sidecar must be a regular file")
    if observed.st_size > MAX_SNAPSHOT_MANIFEST_BYTES:
        raise error_type("snapshot sidecar is too large")

    nofollow = getattr(os, "O_NOFOLLOW", None)
    nonblock = getattr(os, "O_NONBLOCK", None)
    if nofollow is None or nonblock is None:
        raise error_type("snapshot sidecar cannot be opened safely")
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | nofollow | nonblock)
        opened = os.fstat(descriptor)
        if not _manifest_stat_matches(observed, opened):
            raise error_type("snapshot sidecar changed while opening")
        if opened.st_size > MAX_SNAPSHOT_MANIFEST_BYTES:
            raise error_type("snapshot sidecar is too large")

        data = bytearray()
        while True:
            remaining = MAX_SNAPSHOT_MANIFEST_BYTES + 1 - len(data)
            if remaining <= 0:
                raise error_type("snapshot sidecar is too large")
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > MAX_SNAPSHOT_MANIFEST_BYTES:
                raise error_type("snapshot sidecar is too large")

        finished = os.fstat(descriptor)
        if not _manifest_stat_matches(observed, finished):
            raise error_type("snapshot sidecar changed while reading")
        try:
            current = os.lstat(path)
        except OSError as exc:
            raise error_type("snapshot sidecar changed while reading") from exc
        if not _manifest_stat_matches(observed, current):
            raise error_type("snapshot sidecar changed while reading")
        if len(data) != finished.st_size:
            raise error_type("snapshot sidecar changed while reading")
        return bytes(data)
    except error_type:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise error_type("snapshot sidecar cannot be read") from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError as exc:
                raise error_type(
                    "snapshot sidecar descriptor cannot be closed"
                ) from exc


def filter_snapshot_archive_member(
    info: tarfile.TarInfo,
    root_name: str,
    *,
    error_type: type[Exception],
) -> tarfile.TarInfo:
    """Reject unsafe generated names, links, and special archive entries."""
    normalized = _validate_snapshot_archive_member_name(
        info.name,
        root_name,
        error_type=error_type,
    )
    _validate_snapshot_archive_member_type(
        info,
        normalized,
        root_name,
        error_type=error_type,
    )
    return info


def _manifest_stat_matches(
    expected: os.stat_result,
    observed: os.stat_result,
) -> bool:
    return (
        expected.st_dev,
        expected.st_ino,
        stat.S_IFMT(expected.st_mode),
        expected.st_size,
    ) == (
        observed.st_dev,
        observed.st_ino,
        stat.S_IFMT(observed.st_mode),
        observed.st_size,
    )


def _validate_snapshot_archive_member_type(
    info: tarfile.TarInfo,
    normalized: str,
    root_name: str,
    *,
    error_type: type[Exception],
) -> None:
    if info.issym() or info.islnk():
        raise error_type("archive contains a link member")
    if normalized.rsplit("/", 1)[-1] == ".git" and not info.isdir():
        raise error_type("archive Git metadata entry is not a directory")
    if not (info.isdir() or info.isfile()):
        raise error_type("archive contains a non-portable special entry")


def validate_snapshot_archive_members(
    archive: Path,
    root_name: str,
    *,
    error_type: type[Exception],
    max_members: int | None = MAX_SNAPSHOT_ARCHIVE_MEMBERS,
) -> None:
    """Validate archive member names, types, root, and parent directories."""
    saw_root = False
    seen: set[str] = set()
    member_types: dict[str, str] = {}
    try:
        with tarfile.open(archive, mode="r:*") as tar:
            member_count = 0
            while (info := tar.next()) is not None:
                tar.members.clear()
                member_count += 1
                if max_members is not None and member_count > max_members:
                    raise error_type("archive contains too many members")
                normalized = _validate_snapshot_archive_member_name(
                    info.name,
                    root_name,
                    error_type=error_type,
                )
                if normalized in seen:
                    raise error_type("archive contains duplicate members")
                seen.add(normalized)
                if normalized == root_name:
                    if not info.isdir():
                        raise error_type("archive root member is not a directory")
                    saw_root = True
                _validate_snapshot_archive_member_type(
                    info,
                    normalized,
                    root_name,
                    error_type=error_type,
                )
                if info.isdir():
                    member_types[normalized] = "directory"
                else:
                    member_types[normalized] = "file"
    except (OSError, tarfile.TarError) as exc:
        raise error_type("snapshot archive is not a readable tar archive") from exc
    if not saw_root:
        raise error_type("archive does not contain its top-level root directory")

    for member_name in member_types:
        parent_parts = member_name.split("/")[:-1]
        for index in range(1, len(parent_parts) + 1):
            parent_name = "/".join(parent_parts[:index])
            if member_types.get(parent_name) != "directory":
                raise error_type("archive member parent is not a directory")


def _validate_snapshot_archive_member_name(
    name: str,
    root_name: str,
    *,
    error_type: type[Exception],
) -> str:
    if not isinstance(name, str) or not name or "\x00" in name:
        raise error_type("archive contains an unsafe member name")
    if name.startswith(("/", "\\")) or _ARCHIVE_WINDOWS_ABSOLUTE_RE.match(name):
        raise error_type("archive contains an absolute member name")
    if "\\" in name or _ARCHIVE_CONTROL_RE.search(name):
        raise error_type("archive contains an unsafe member name")
    parts = name.split("/")
    while parts and parts[-1] == "":
        parts.pop()
    if not parts or parts[0] != root_name:
        raise error_type("archive member is outside its single top-level root")
    if any(part in {"", ".", ".."} for part in parts[1:]):
        raise error_type("archive member is outside its single top-level root")
    if any(part == "" for part in parts):
        raise error_type("archive contains an unsafe member name")
    return "/".join(parts)
