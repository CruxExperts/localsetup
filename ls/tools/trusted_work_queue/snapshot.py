"""Portable full-repository snapshots for the trusted work queue.

The implementation deliberately uses only the Python standard library.  A
snapshot is a streamed gzip-compressed POSIX/PAX tar archive containing one
top-level repository directory.  Its sidecar is deterministic JSON metadata;
it does not contain a file list or file contents.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import stat
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FORMAT_VERSION = 1
MANIFEST_SUFFIX = ".manifest.json"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_OBJECT_RE = re.compile(r"^[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?$")
_SAFE_ROOT_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class SnapshotError(Exception):
    """Base error for snapshot creation and validation failures."""


class SnapshotValidationError(SnapshotError):
    """Raised when an archive or its sidecar fails validation."""


@dataclass(frozen=True)
class SnapshotMetadata:
    """The complete, safe metadata contract stored in a sidecar manifest."""

    format_version: int
    source_root_name: str
    archive_sha256: str
    total_bytes: int
    git_head: str | None
    job_id: str
    job_identity: str | None = None
    prd_identity: str | None = None
    master_remote: str | None = None
    master_ref: str | None = None
    source_fork: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return the manifest representation in its stable field names."""
        return {
            "format_version": self.format_version,
            "source_root_name": self.source_root_name,
            "archive_sha256": self.archive_sha256,
            "total_bytes": self.total_bytes,
            "git_head": self.git_head,
            "job_id": self.job_id,
            "job_identity": self.job_identity,
            "prd_identity": self.prd_identity,
            "master_remote": self.master_remote,
            "master_ref": self.master_ref,
            "source_fork": self.source_fork,
        }


@dataclass(frozen=True)
class SnapshotResult:
    """Paths and metadata returned after a successful snapshot operation."""

    archive_path: Path
    manifest_path: Path
    metadata: SnapshotMetadata


def manifest_path_for(archive_path: os.PathLike[str] | str) -> Path:
    """Return the required sidecar path for *archive_path*.

    The sidecar is adjacent to the archive and appends ``.manifest.json`` to
    the complete archive filename (for example, ``repo.tar`` becomes
    ``repo.tar.manifest.json``).
    """
    archive = Path(archive_path)
    return archive.with_name(archive.name + MANIFEST_SUFFIX)


def job_id_for_metadata(
    *,
    format_version: int,
    source_root_name: str,
    archive_sha256: str,
    total_bytes: int,
    git_head: str | None,
) -> str:
    """Derive the deterministic job id from the safe metadata fields only."""
    identity = {
        "archive_sha256": archive_sha256,
        "format_version": format_version,
        "git_head": git_head,
        "source_root_name": source_root_name,
        "total_bytes": total_bytes,
    }
    encoded = json.dumps(
        identity,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def create_snapshot(
    source_dir: os.PathLike[str] | str,
    archive_path: os.PathLike[str] | str,
) -> SnapshotResult:
    """Create a complete repository tar.gz archive and deterministic sidecar.

    ``source_dir`` must be an existing directory.  Every directory entry is
    included, including hidden paths and ``.git``.  Symbolic links are stored
    as links and are never traversed.  FIFOs, sockets, device nodes, and any
    other non-portable special entries are rejected before an archive is
    committed.  The archive output must be outside the source tree.
    """
    source = _resolve_source_dir(source_dir)
    root_name = _safe_root_name(source.name)
    archive = _prepare_archive_path(source, archive_path)
    manifest = manifest_path_for(archive)
    if os.path.lexists(archive) or os.path.lexists(manifest):
        raise SnapshotError(
            "snapshot archive or adjacent manifest already exists; use a unique packet path"
        )
    _scan_source_tree(source)
    git_head_before = _discover_git_head(source)

    archive.parent.mkdir(parents=True, exist_ok=True)
    temporary_archive: Path | None = None
    try:
        temporary_archive = _temporary_path(archive)
        with temporary_archive.open("wb") as raw_archive:
            hashing_writer = _HashingWriter(raw_archive)
            with gzip.GzipFile(
                fileobj=hashing_writer,
                mode="wb",
                filename="",
                mtime=0,
            ) as compressed_archive:
                with tarfile.open(
                    name=str(temporary_archive),
                    fileobj=compressed_archive,
                    mode="w|",
                    format=tarfile.PAX_FORMAT,
                    dereference=False,
                ) as tar:
                    tar.add(
                        source,
                        arcname=root_name,
                        recursive=True,
                        filter=lambda info: _archive_filter(info, root_name),
                    )
            raw_archive.flush()
            os.fsync(raw_archive.fileno())
            archive_sha256 = hashing_writer.hexdigest()
            total_bytes = hashing_writer.total_bytes
        git_head_after = _discover_git_head(source)
        if git_head_after != git_head_before:
            raise SnapshotError("source Git HEAD changed while the snapshot streamed")
        git_head = git_head_before
        _publish_no_clobber(temporary_archive, archive)
        temporary_archive = None
    except (OSError, tarfile.TarError, SnapshotError) as exc:
        if temporary_archive is not None:
            _unlink_quietly(temporary_archive)
        if isinstance(exc, SnapshotError):
            raise
        raise SnapshotError("unable to create the snapshot archive") from exc

    job_id = job_id_for_metadata(
        format_version=FORMAT_VERSION,
        source_root_name=root_name,
        archive_sha256=archive_sha256,
        total_bytes=total_bytes,
        git_head=git_head,
    )
    metadata = SnapshotMetadata(
        format_version=FORMAT_VERSION,
        source_root_name=root_name,
        archive_sha256=archive_sha256,
        total_bytes=total_bytes,
        git_head=git_head,
        job_id=job_id,
    )
    try:
        _write_manifest(manifest, metadata)
    except SnapshotError:
        _unlink_quietly(archive)
        try:
            _fsync_parent(archive)
        except SnapshotError:
            pass
        raise
    return SnapshotResult(archive, manifest, metadata)


def validate_snapshot(
    archive_path: os.PathLike[str] | str,
    manifest_path: os.PathLike[str] | str | None = None,
) -> SnapshotMetadata:
    """Validate an archive and its adjacent sidecar without extracting.

    Validation checks the exact sidecar pairing, metadata schema and job id,
    archive byte count and SHA-256, one-root member containment, allowed tar
    member types, and the presence of the root directory entry.
    """
    archive = Path(archive_path)
    expected_manifest = manifest_path_for(archive)
    manifest = expected_manifest if manifest_path is None else Path(manifest_path)
    if _resolved_path(manifest) != _resolved_path(expected_manifest):
        raise SnapshotValidationError("manifest is not the archive's adjacent sidecar")
    if not archive.is_file():
        raise SnapshotValidationError("snapshot archive does not exist or is not a file")
    if not manifest.is_file():
        raise SnapshotValidationError("snapshot sidecar does not exist or is not a file")

    metadata = _read_manifest(manifest)
    try:
        archive_size = archive.stat().st_size
    except OSError as exc:
        raise SnapshotValidationError("cannot stat snapshot archive") from exc
    if archive_size != metadata.total_bytes:
        raise SnapshotValidationError("snapshot archive byte count does not match sidecar")
    if _sha256_file(archive) != metadata.archive_sha256:
        raise SnapshotValidationError("snapshot archive SHA-256 does not match sidecar")

    _validate_archive_members(archive, metadata.source_root_name)
    return metadata


def _resolve_source_dir(source_dir: os.PathLike[str] | str) -> Path:
    source = Path(source_dir).expanduser()
    try:
        resolved = source.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise SnapshotError("source repository directory does not exist") from exc
    if not resolved.is_dir():
        raise SnapshotError("source repository path is not a directory")
    return resolved


def _prepare_archive_path(source: Path, archive_path: os.PathLike[str] | str) -> Path:
    archive = Path(archive_path).expanduser()
    if not archive.name:
        raise SnapshotError("output archive path must name a file")
    try:
        resolved_archive = archive.resolve(strict=False)
        resolved_archive.relative_to(source)
    except ValueError:
        pass
    except (OSError, RuntimeError) as exc:
        raise SnapshotError("cannot resolve output archive path") from exc
    else:
        raise SnapshotError("output archive path must be outside the source tree")
    return archive


def _safe_root_name(name: str) -> str:
    if not name or name in {".", ".."} or not _SAFE_ROOT_RE.fullmatch(name):
        raise SnapshotError("source directory basename is not a safe archive root")
    return name


def _scan_source_tree(source: Path) -> None:
    """Reject non-portable filesystem entries without following symlinks."""
    pending = [source]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as scan:
                entries = sorted(scan, key=lambda entry: entry.name)
        except OSError as exc:
            raise SnapshotError("cannot read the source repository directory") from exc
        for entry in entries:
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise SnapshotError("cannot inspect a source repository entry") from exc
            mode = stat.S_IFMT(info.st_mode)
            relative = Path(os.path.relpath(entry.path, source))
            if stat.S_ISDIR(mode):
                pending.append(Path(entry.path))
            elif stat.S_ISREG(mode) or stat.S_ISLNK(mode):
                continue
            else:
                raise SnapshotError(
                    "source contains a non-portable special entry: "
                    + relative.as_posix()
                )


def _archive_filter(info: tarfile.TarInfo, root_name: str) -> tarfile.TarInfo:
    """Reject a race-created special entry and unsafe generated member name."""
    _validate_member_name(info.name, root_name, SnapshotError)
    if not (info.isdir() or info.isfile() or info.issym() or info.islnk()):
        raise SnapshotError("archive contains a non-portable special entry")
    return info


def _validate_archive_members(archive: Path, root_name: str) -> None:
    saw_root = False
    seen: set[str] = set()
    try:
        with tarfile.open(archive, mode="r:*") as tar:
            for info in tar:
                normalized = _validate_member_name(
                    info.name, root_name, SnapshotValidationError
                )
                if normalized in seen:
                    raise SnapshotValidationError("archive contains duplicate members")
                seen.add(normalized)
                if normalized == root_name:
                    if not info.isdir():
                        raise SnapshotValidationError("archive root member is not a directory")
                    saw_root = True
                if not (info.isdir() or info.isfile() or info.issym() or info.islnk()):
                    raise SnapshotValidationError("archive contains a non-portable special member")
                if info.islnk():
                    _validate_member_name(
                        info.linkname,
                        root_name,
                        SnapshotValidationError,
                    )
    except SnapshotValidationError:
        raise
    except (OSError, tarfile.TarError) as exc:
        raise SnapshotValidationError("snapshot archive is not a readable tar archive") from exc
    if not saw_root:
        raise SnapshotValidationError("archive does not contain its top-level root directory")


def _validate_member_name(
    name: str,
    root_name: str,
    error_type: type[SnapshotError],
) -> str:
    if not isinstance(name, str) or not name or "\x00" in name:
        raise error_type("archive contains an unsafe member name")
    if name.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:[\\/]", name):
        raise error_type("archive contains an absolute member name")
    if "\\" in name or _CONTROL_RE.search(name):
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


def _read_manifest(path: Path) -> SnapshotMetadata:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SnapshotValidationError("snapshot sidecar is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise SnapshotValidationError("snapshot sidecar must contain a JSON object")
    required = {
        "format_version",
        "source_root_name",
        "archive_sha256",
        "total_bytes",
        "git_head",
        "job_id",
        "job_identity",
        "prd_identity",
        "master_remote",
        "master_ref",
        "source_fork",
    }
    if set(payload) != required:
        raise SnapshotValidationError("snapshot sidecar fields do not match the contract")
    format_version = payload["format_version"]
    root_name = payload["source_root_name"]
    archive_sha256 = payload["archive_sha256"]
    total_bytes = payload["total_bytes"]
    git_head = payload["git_head"]
    job_id = payload["job_id"]
    job_identity = payload["job_identity"]
    prd_identity = payload["prd_identity"]
    master_remote = payload["master_remote"]
    master_ref = payload["master_ref"]
    source_fork = payload["source_fork"]
    if format_version != FORMAT_VERSION:
        raise SnapshotValidationError("unsupported snapshot format version")
    if (
        not isinstance(root_name, str)
        or root_name in {".", ".."}
        or not _SAFE_ROOT_RE.fullmatch(root_name)
    ):
        raise SnapshotValidationError("snapshot sidecar has an unsafe source root name")
    if not isinstance(archive_sha256, str) or not _SHA256_RE.fullmatch(archive_sha256):
        raise SnapshotValidationError("snapshot sidecar has an invalid archive SHA-256")
    if isinstance(total_bytes, bool) or not isinstance(total_bytes, int) or total_bytes < 0:
        raise SnapshotValidationError("snapshot sidecar has an invalid byte count")
    if git_head is not None and (
        not isinstance(git_head, str) or not _GIT_OBJECT_RE.fullmatch(git_head)
    ):
        raise SnapshotValidationError("snapshot sidecar has an invalid Git HEAD")
    if not isinstance(job_id, str) or not _SHA256_RE.fullmatch(job_id):
        raise SnapshotValidationError("snapshot sidecar has an invalid job id")
    if job_identity is not None and not isinstance(job_identity, str):
        raise SnapshotValidationError("snapshot sidecar has an invalid opaque job identity")
    if prd_identity is not None and not isinstance(prd_identity, str):
        raise SnapshotValidationError("snapshot sidecar has an invalid opaque PRD identity")
    if master_remote is not None and not isinstance(master_remote, str):
        raise SnapshotValidationError("snapshot sidecar has an invalid master remote identity")
    if master_ref is not None and not isinstance(master_ref, str):
        raise SnapshotValidationError("snapshot sidecar has an invalid master ref")
    if source_fork is not None and not isinstance(source_fork, str):
        raise SnapshotValidationError("snapshot sidecar has an invalid source fork identity")
    expected_job_id = job_id_for_metadata(
        format_version=format_version,
        source_root_name=root_name,
        archive_sha256=archive_sha256,
        total_bytes=total_bytes,
        git_head=git_head,
    )
    if job_id != expected_job_id:
        raise SnapshotValidationError("snapshot sidecar job id does not match metadata")
    return SnapshotMetadata(
        format_version=format_version,
        source_root_name=root_name,
        archive_sha256=archive_sha256,
        total_bytes=total_bytes,
        git_head=git_head,
        job_id=job_id,
        job_identity=job_identity,
        prd_identity=prd_identity,
        master_remote=master_remote,
        master_ref=master_ref,
        source_fork=source_fork,
    )


def _write_manifest(path: Path, metadata: SnapshotMetadata) -> None:
    temporary: Path | None = None
    try:
        temporary = _temporary_path(path)
        with temporary.open("w", encoding="ascii", newline="\n") as handle:
            json.dump(
                metadata.as_dict(),
                handle,
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        _publish_no_clobber(temporary, path)
        temporary = None
    except OSError as exc:
        raise SnapshotError("unable to write the snapshot sidecar") from exc
    finally:
        if temporary is not None:
            _unlink_quietly(temporary)



def _publish_no_clobber(temporary: Path, destination: Path) -> None:
    """Publish a same-filesystem temporary file without replacing an existing path."""
    try:
        os.link(temporary, destination)
    except FileExistsError as exc:
        raise SnapshotError(
            "snapshot archive or adjacent manifest already exists; use a unique packet path"
        ) from exc
    except OSError as exc:
        raise SnapshotError("unable to publish the snapshot artifact") from exc
    try:
        _fsync_parent(destination)
    except SnapshotError:
        _unlink_if_same_inode(temporary, destination)
        try:
            _fsync_parent(destination)
        except SnapshotError:
            pass
        raise
    _unlink_quietly(temporary)


def _unlink_if_same_inode(expected: Path, destination: Path) -> None:
    try:
        expected_stat = expected.stat()
        destination_stat = destination.stat()
        if (
            expected_stat.st_dev == destination_stat.st_dev
            and expected_stat.st_ino == destination_stat.st_ino
        ):
            destination.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _temporary_path(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="wb",
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        delete=False,
    )
    temporary = Path(handle.name)
    handle.close()
    return temporary


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise SnapshotValidationError("unable to read the snapshot archive") from exc
    return digest.hexdigest()


class _HashingWriter:
    """Write-through archive sink that hashes compressed bytes as they stream."""

    def __init__(self, raw: Any) -> None:
        self._raw = raw
        self._digest = hashlib.sha256()
        self.total_bytes = 0

    def write(self, data: bytes) -> int:
        written = self._raw.write(data)
        if written is None:
            written = len(data)
        if written != len(data):
            if written > 0:
                self._digest.update(data[:written])
                self.total_bytes += written
            raise OSError("short write while streaming the snapshot archive")
        self._digest.update(data)
        self.total_bytes += written
        return written

    def flush(self) -> None:
        self._raw.flush()

    def fileno(self) -> int:
        return self._raw.fileno()

    def hexdigest(self) -> str:
        return self._digest.hexdigest()


def _fsync_parent(path: Path) -> None:
    try:
        directory_fd = os.open(path.parent, os.O_RDONLY)
    except OSError as exc:
        raise SnapshotError("unable to sync the snapshot destination") from exc
    try:
        os.fsync(directory_fd)
    except OSError as exc:
        raise SnapshotError("unable to sync the snapshot destination") from exc
    finally:
        os.close(directory_fd)


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _resolved_path(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise SnapshotValidationError("cannot resolve snapshot sidecar path") from exc


def _discover_git_head(source: Path) -> str | None:
    """Read a full Git object id from HEAD without invoking Git or exposing data."""
    git_entry = source / ".git"
    try:
        if git_entry.is_dir():
            git_dir = git_entry.resolve(strict=True)
        elif git_entry.is_file():
            text = git_entry.read_text(encoding="utf-8", errors="replace")
            prefix = "gitdir:"
            if not text.startswith(prefix):
                return None
            location = text[len(prefix) :].strip()
            if not location or _CONTROL_RE.search(location):
                return None
            git_dir = (git_entry.parent / location).resolve(strict=True)
        else:
            return None
        if not git_dir.is_dir():
            return None
        head = _read_git_text(git_dir / "HEAD")
        if head is None:
            return None
        line = head.strip()
        if _GIT_OBJECT_RE.fullmatch(line):
            return line.lower()
        if not line.startswith("ref: "):
            return None
        ref = line[5:].strip()
        if not _safe_git_ref(ref):
            return None
        git_dirs = [git_dir]
        commondir = _read_git_text(git_dir / "commondir")
        if commondir is not None:
            common_location = commondir.strip()
            if common_location and not _CONTROL_RE.search(common_location):
                common_dir = (git_dir / common_location).resolve(strict=True)
                if common_dir.is_dir() and common_dir != git_dir:
                    git_dirs.append(common_dir)
        for candidate_dir in git_dirs:
            target = _read_git_text(candidate_dir / ref)
            if target is not None:
                candidate = target.strip()
                if _GIT_OBJECT_RE.fullmatch(candidate):
                    return candidate.lower()
        for candidate_dir in git_dirs:
            packed = _read_git_text(candidate_dir / "packed-refs")
            if packed is None:
                continue
            for packed_line in packed.splitlines():
                if packed_line.startswith(("#", "^")):
                    continue
                fields = packed_line.split()
                if (
                    len(fields) == 2
                    and fields[1] == ref
                    and _GIT_OBJECT_RE.fullmatch(fields[0])
                ):
                    return fields[0].lower()
    except (OSError, RuntimeError, UnicodeError):
        return None
    return None


def _read_git_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="ascii")
    except (OSError, UnicodeError):
        return None


def _safe_git_ref(ref: str) -> bool:
    if not ref.startswith("refs/") or _CONTROL_RE.search(ref):
        return False
    parts = ref.split("/")
    return all(part not in {"", ".", ".."} for part in parts)


__all__ = [
    "FORMAT_VERSION",
    "MANIFEST_SUFFIX",
    "SnapshotError",
    "SnapshotMetadata",
    "SnapshotResult",
    "SnapshotValidationError",
    "create_snapshot",
    "job_id_for_metadata",
    "manifest_path_for",
    "validate_snapshot",
]
