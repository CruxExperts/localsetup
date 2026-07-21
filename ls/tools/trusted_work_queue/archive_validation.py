"""Validate portable archive member names, types, and parent structure."""

from __future__ import annotations

import re
import tarfile
from pathlib import Path

_ARCHIVE_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_ARCHIVE_WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")


def filter_snapshot_archive_member(
    info: tarfile.TarInfo,
    root_name: str,
    *,
    error_type: type[Exception],
) -> tarfile.TarInfo:
    """Reject unsafe generated names, links, and special archive entries."""
    _validate_snapshot_archive_member_name(
        info.name,
        root_name,
        error_type=error_type,
    )
    if info.issym() or info.islnk():
        raise error_type("archive contains a link member")
    if not (info.isdir() or info.isfile()):
        raise error_type("archive contains a non-portable special entry")
    return info


def validate_snapshot_archive_members(
    archive: Path,
    root_name: str,
    *,
    error_type: type[Exception],
) -> None:
    """Validate archive member names, types, root, and parent directories."""
    saw_root = False
    seen: set[str] = set()
    member_types: dict[str, str] = {}
    try:
        with tarfile.open(archive, mode="r:*") as tar:
            for info in tar:
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
                if info.issym() or info.islnk():
                    raise error_type("archive contains a link member")
                if info.isdir():
                    member_types[normalized] = "directory"
                elif info.isfile():
                    member_types[normalized] = "file"
                else:
                    raise error_type("archive contains a non-portable special member")
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
