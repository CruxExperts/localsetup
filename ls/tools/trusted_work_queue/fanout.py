"""Detached, offline materialization for claimed trusted-work-queue packets.

A materializer claims the deterministic oldest shared-folder packet, validates its
archive and opaque PRD, then publishes exactly the requested number of isolated
candidate directories.  It deliberately does not execute repository code, parse
the PRD, select a model, make network requests, or delete the retained claim.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tarfile
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

try:
    from .shared_folder import QueueClaim, QueuePacket, SharedFolderError, claim_oldest_packet, load_packet
    from .snapshot import SnapshotError, SnapshotMetadata, validate_snapshot_contents
except ImportError:  # pragma: no cover - supports direct script execution.
    from shared_folder import QueueClaim, QueuePacket, SharedFolderError, claim_oldest_packet, load_packet  # type: ignore
    from snapshot import SnapshotError, SnapshotMetadata, validate_snapshot_contents  # type: ignore

FANOUT_FORMAT_VERSION = 1
FANOUT_FILENAME = "fanout.json"
CANDIDATE_PREFIX = "candidate-"
PRD_FILENAME = "prd.bin"
_COPY_CHUNK_BYTES = 1024 * 1024


class FanoutError(Exception):
    """A claimed packet cannot be safely materialized into candidates."""


@dataclass(frozen=True)
class CandidateReplica:
    """One durable isolated snapshot plus its verbatim opaque PRD copy."""

    candidate_id: str
    candidate_dir: Path
    source_dir: Path
    prd_path: Path


@dataclass(frozen=True)
class CandidateFanout:
    """A published set of candidate replicas tied to one retained claim."""

    job_dir: Path
    manifest_path: Path
    packet: QueuePacket
    candidates: tuple[CandidateReplica, ...]


def materialize_oldest_claim(
    queue_root: str | os.PathLike[str],
    candidate_root: str | os.PathLike[str],
) -> CandidateFanout | None:
    """Claim and materialize the deterministic oldest packet, or return ``None``.

    The claimed queue packet is intentionally retained.  A later result-validation
    phase owns reconciliation and any explicit retention/deletion transition.
    """
    claim = claim_oldest_packet(queue_root)
    if claim is None:
        return None
    return materialize_claim(claim, candidate_root)


def materialize_claim(claim: QueueClaim, candidate_root: str | os.PathLike[str]) -> CandidateFanout:
    """Materialize exactly ``replication_count`` isolated candidates for ``claim``.

    The archive is copied through one private, descriptor-bound staging file.
    A permanent job-directory reservation is then acquired atomically; candidate
    directories are created beneath it and ``fanout.json`` is written last as the
    sole readiness marker. A failed materialization leaves no ready manifest.
    """
    packet = _reload_claimed_packet(claim)
    root = _prepare_candidate_root(candidate_root)
    job_dir = root / packet.job_id
    if os.path.lexists(job_dir):
        raise FanoutError("candidate output already exists for this snapshot job")

    stage_dir = root / f".{packet.job_id}.{uuid.uuid4().hex}.stage"
    try:
        os.mkdir(stage_dir, 0o700)
        os.chmod(stage_dir, 0o700)
        _fsync_directory(root)
        staged_archive = _stage_snapshot(packet, stage_dir)
        _reserve_job_dir(job_dir)
        with _open_staged_snapshot(staged_archive, packet.snapshot) as staged_handle:
            staged_baseline = os.fstat(staged_handle.fileno())
            candidates = tuple(
                _materialize_candidate(packet, job_dir, staged_handle, index)
                for index in range(1, packet.replication_count + 1)
            )
            _verify_staged_snapshot(staged_handle, packet.snapshot, staged_baseline)
        _fsync_directory(job_dir)
        manifest_path = job_dir / FANOUT_FILENAME
        _write_manifest_no_clobber(manifest_path, packet, candidates)
        return CandidateFanout(
            job_dir=job_dir,
            manifest_path=manifest_path,
            packet=packet,
            candidates=candidates,
        )
    except FanoutError:
        raise
    except (OSError, tarfile.TarError) as exc:
        raise FanoutError("cannot materialize claimed queue packet") from exc
    finally:
        if stage_dir.exists() or stage_dir.is_symlink():
            shutil.rmtree(stage_dir, ignore_errors=True)

def _reload_claimed_packet(claim: QueueClaim) -> QueuePacket:
    """Re-read the retained claim so stale or redirected inputs cannot fan out."""
    marker = Path(claim.claim_marker)
    packet_dir = Path(claim.packet.packet_dir)
    try:
        marker_mode = marker.lstat().st_mode
    except OSError as exc:
        raise FanoutError("queue claim marker cannot be inspected") from exc
    if not stat.S_ISREG(marker_mode):
        raise FanoutError("queue claim marker is unavailable")
    try:
        packet = load_packet(packet_dir)
    except SharedFolderError as exc:
        raise FanoutError("claimed queue packet cannot be validated") from exc
    if packet.job_id != claim.packet.job_id:
        raise FanoutError("claimed queue packet identity changed")
    return packet


def _canonical_candidate_root(value: str | os.PathLike[str]) -> Path:
    """Resolve existing ancestors while preserving the final root name."""
    requested = Path(value).expanduser()
    if not requested.name or requested.name in {".", ".."}:
        raise FanoutError("candidate root must name a directory")
    try:
        physical_parent = requested.parent.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise FanoutError("candidate root parent cannot be resolved") from exc
    return physical_parent / requested.name


def _directory_stat(path: Path, *, field: str) -> os.stat_result:
    try:
        result = path.lstat()
    except OSError as exc:
        raise FanoutError(f"{field} cannot be inspected") from exc
    if stat.S_ISLNK(result.st_mode) or not stat.S_ISDIR(result.st_mode):
        raise FanoutError(f"{field} must be a non-symlink directory")
    return result


def _validate_higher_directory(path: Path) -> None:
    result = _directory_stat(path, field="candidate root ancestor")
    if result.st_uid not in {0, os.geteuid()}:
        raise FanoutError("candidate root ancestor has an unexpected owner")
    if result.st_mode & 0o022 and not (
        result.st_uid == 0 and result.st_mode & stat.S_ISVTX
    ):
        raise FanoutError("candidate root ancestor must not be writable")


def _validate_candidate_root_ancestors(root: Path) -> None:
    """Validate the anchored parent chain before using candidate output."""
    direct_parent = root.parent
    direct = _directory_stat(direct_parent, field="candidate root parent")
    if direct.st_uid != os.geteuid() or direct.st_mode & 0o022:
        raise FanoutError("candidate root parent must be private and euid-owned")
    for ancestor in direct_parent.parents:
        _validate_higher_directory(ancestor)


def _create_candidate_root_parents(root: Path) -> None:
    """Create missing physical parents securely, syncing each parent entry."""
    parent = root.parent
    missing: list[Path] = []
    while not os.path.lexists(parent):
        missing.append(parent)
        if parent == parent.parent:
            raise FanoutError("candidate root parent cannot be inspected")
        parent = parent.parent
    _validate_higher_directory(parent)
    for ancestor in parent.parents:
        _validate_higher_directory(ancestor)
    for path in reversed(missing):
        created = False
        try:
            os.mkdir(path, 0o700)
            created = True
        except FileExistsError:
            pass
        except OSError as exc:
            raise FanoutError("candidate root parent cannot be created") from exc
        if created:
            try:
                os.chmod(path, 0o700)
            except OSError as exc:
                raise FanoutError("candidate root parent cannot be secured") from exc
        _directory_stat(path, field="candidate root parent")
        _fsync_directory(path.parent)


def _prepare_candidate_root(value: str | os.PathLike[str]) -> Path:
    root = _canonical_candidate_root(value)
    _create_candidate_root_parents(root)
    _validate_candidate_root_ancestors(root)
    try:
        if not os.path.lexists(root):
            os.mkdir(root, 0o700)
            os.chmod(root, 0o700)
            _fsync_directory(root.parent)
        mode = root.lstat().st_mode
        root_stat = root.lstat()
    except FileExistsError:
        try:
            mode = root.lstat().st_mode
            root_stat = root.lstat()
        except OSError as exc:
            raise FanoutError("candidate root cannot be inspected") from exc
    except OSError as exc:
        raise FanoutError("candidate root cannot be inspected") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise FanoutError("candidate root must be non-symlink directory")
    if root_stat.st_uid != os.geteuid():
        raise FanoutError("candidate root must be owned by the current user")
    elif mode & 0o077:
        raise FanoutError("candidate root must be owner-only")
    _validate_candidate_root_ancestors(root)
    _fsync_directory(root)
    return root




def _stage_snapshot(packet: QueuePacket, stage_dir: Path) -> Path:
    """Copy and validate the claimed archive through one opened descriptor."""
    staged_archive = stage_dir / ".snapshot.tar.gz"
    digest = hashlib.sha256()
    total = 0
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(packet.archive_path, flags)
        source_stat = os.fstat(descriptor)
        if not stat.S_ISREG(source_stat.st_mode) or source_stat.st_nlink != 1:
            raise FanoutError("claimed snapshot archive is unavailable")
        source = os.fdopen(descriptor, "rb", closefd=True)
        descriptor = None
        with source, staged_archive.open("xb") as destination:
            while chunk := source.read(_COPY_CHUNK_BYTES):
                digest.update(chunk)
                total += len(chunk)
                destination.write(chunk)
            destination.flush()
            os.chmod(staged_archive, 0o600)
            os.fsync(destination.fileno())
    except FanoutError:
        raise
    except OSError as exc:
        raise FanoutError("claimed snapshot archive cannot be staged") from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
    if digest.hexdigest() != packet.snapshot.archive_sha256 or total != packet.snapshot.total_bytes:
        raise FanoutError("claimed snapshot archive changed during staging")
    _validated_snapshot_contents(staged_archive, packet.snapshot)
    _fsync_directory(stage_dir)
    return staged_archive


def _open_staged_snapshot(path: Path, expected: SnapshotMetadata) -> BinaryIO:
    """Open the staged archive once and bind later extraction to its inode."""
    digest = hashlib.sha256()
    total = 0
    descriptor: int | None = None
    source: BinaryIO | None = None
    try:
        flags = os.O_RDONLY
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        staged_stat = os.fstat(descriptor)
        if not stat.S_ISREG(staged_stat.st_mode) or staged_stat.st_nlink != 1:
            raise FanoutError("staged snapshot archive is unavailable")
        source = os.fdopen(descriptor, "rb", closefd=True)
        descriptor = None
        while chunk := source.read(_COPY_CHUNK_BYTES):
            digest.update(chunk)
            total += len(chunk)
        if digest.hexdigest() != expected.archive_sha256 or total != expected.total_bytes:
            raise FanoutError("staged snapshot archive changed before extraction")
        source.seek(0)
        path.unlink()
        return source
    except FanoutError:
        if source is not None:
            source.close()
        raise
    except OSError as exc:
        if source is not None:
            source.close()
        raise FanoutError("staged snapshot archive cannot be opened") from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _verify_staged_snapshot(
    source: BinaryIO,
    expected: SnapshotMetadata,
    baseline: os.stat_result,
) -> None:
    """Confirm the bound archive descriptor stayed unchanged during extraction."""
    try:
        current = os.fstat(source.fileno())
        if current.st_size != baseline.st_size or current.st_ctime_ns != baseline.st_ctime_ns:
            raise FanoutError("staged snapshot archive changed during extraction")
        source.seek(0)
        digest = hashlib.sha256()
        total = 0
        while chunk := source.read(_COPY_CHUNK_BYTES):
            digest.update(chunk)
            total += len(chunk)
        if digest.hexdigest() != expected.archive_sha256 or total != expected.total_bytes:
            raise FanoutError("staged snapshot archive changed during extraction")
        source.seek(0)
    except FanoutError:
        raise
    except OSError as exc:
        raise FanoutError("staged snapshot archive cannot be verified") from exc


def _reserve_job_dir(path: Path) -> None:
    """Permanently reserve a job path without replacement semantics."""
    try:
        os.mkdir(path, 0o700)
        os.chmod(path, 0o700)
        _fsync_directory(path.parent)
    except FileExistsError as exc:
        raise FanoutError("candidate output already exists for this snapshot job") from exc
    except OSError as exc:
        raise FanoutError("candidate output cannot be reserved") from exc


def _materialize_candidate(
    packet: QueuePacket,
    stage_dir: Path,
    staged_archive: Path | BinaryIO,
    index: int,
) -> CandidateReplica:
    candidate_id = f"{CANDIDATE_PREFIX}{index:03d}"
    candidate_dir = stage_dir / candidate_id
    source_dir = candidate_dir / packet.snapshot.source_root_name
    try:
        os.mkdir(candidate_dir, 0o700)
        os.chmod(candidate_dir, 0o700)
        _extract_snapshot(staged_archive, packet.snapshot, candidate_dir)
        _copy_prd(packet.prd_path, candidate_dir / PRD_FILENAME, packet)
        _fsync_directory(candidate_dir)
    except FanoutError:
        raise
    except OSError as exc:
        raise FanoutError("cannot materialize candidate replica") from exc
    return CandidateReplica(
        candidate_id=candidate_id,
        candidate_dir=candidate_dir,
        source_dir=source_dir,
        prd_path=candidate_dir / PRD_FILENAME,
    )


def _extract_snapshot(archive: Path | BinaryIO, metadata: SnapshotMetadata, destination: Path) -> None:
    """Extract a staged archive with explicit member path and type handling."""
    directory_fds: dict[Path, int] = {}
    try:
        if isinstance(archive, Path):
            _validated_snapshot_contents(archive, metadata)
            tar = tarfile.open(archive, mode="r:*")
        else:
            archive.seek(0)
            tar = tarfile.open(fileobj=archive, mode="r:*")
        with tar:
            members = list(tar)
            destinations = [
                (_member_destination(member.name, metadata.source_root_name, destination), member)
                for member in members
            ]
            directories = sorted(
                (item for item in destinations if item[1].isdir()),
                key=lambda item: len(item[0].parts),
            )
            for path, _member in directories:
                path.mkdir(mode=0o700, parents=False, exist_ok=False)
                os.chmod(path, 0o700)
                descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
                directory_fds[path] = descriptor
            for path, member in destinations:
                if member.isfile():
                    _extract_regular_file(tar, member, path)
                elif not member.isdir():
                    raise FanoutError("snapshot archive contains a link or special member")
            for path, member in directories:
                os.chmod(path, member.mode & 0o777)
            for path, _member in reversed(directories):
                try:
                    os.fsync(directory_fds[path])
                except OSError as exc:
                    raise FanoutError("snapshot directory cannot be synchronized") from exc
    except FanoutError:
        raise
    except (OSError, tarfile.TarError) as exc:
        raise FanoutError("snapshot archive cannot be extracted") from exc
    finally:
        for descriptor in directory_fds.values():
            try:
                os.close(descriptor)
            except OSError:
                pass


def _validated_snapshot_contents(archive: Path, expected: SnapshotMetadata) -> None:
    try:
        validate_snapshot_contents(archive, expected.source_root_name)
    except SnapshotError as exc:
        raise FanoutError("snapshot archive validation failed") from exc




def _member_destination(name: str, root_name: str, destination: Path) -> Path:
    if not isinstance(name, str) or not name or "\x00" in name:
        raise FanoutError("snapshot archive contains an unsafe member name")
    if name.startswith(("/", "\\")) or "\\" in name:
        raise FanoutError("snapshot archive contains an unsafe member name")
    parts = name.rstrip("/").split("/")
    if not parts or parts[0] != root_name or any(part in {"", ".", ".."} for part in parts):
        raise FanoutError("snapshot archive member is outside its root")
    path = destination.joinpath(*parts)
    try:
        path.relative_to(destination)
    except ValueError as exc:
        raise FanoutError("snapshot archive member is outside its root") from exc
    return path


def _extract_regular_file(tar: tarfile.TarFile, member: tarfile.TarInfo, destination: Path) -> None:
    stream = tar.extractfile(member)
    if stream is None:
        raise FanoutError("snapshot archive regular member cannot be read")
    try:
        with stream, destination.open("xb") as output:
            while chunk := stream.read(_COPY_CHUNK_BYTES):
                output.write(chunk)
            output.flush()
            os.chmod(destination, member.mode & 0o777)
            os.fsync(output.fileno())
    except (OSError, tarfile.TarError) as exc:
        raise FanoutError("snapshot archive regular member cannot be extracted") from exc




def _copy_prd(source: Path, destination: Path, packet: QueuePacket) -> None:
    digest = hashlib.sha256()
    total = 0
    try:
        mode = source.lstat().st_mode
        if not stat.S_ISREG(mode):
            raise FanoutError("claimed PRD is unavailable")
        with source.open("rb") as reader, destination.open("xb") as writer:
            while chunk := reader.read(_COPY_CHUNK_BYTES):
                digest.update(chunk)
                total += len(chunk)
                writer.write(chunk)
            writer.flush()
            os.chmod(destination, 0o600)
            os.fsync(writer.fileno())
    except FanoutError:
        raise
    except OSError as exc:
        raise FanoutError("claimed PRD cannot be copied") from exc
    if digest.hexdigest() != packet.prd_sha256 or total != packet.prd_bytes:
        raise FanoutError("claimed PRD changed during candidate materialization")


def _write_manifest_no_clobber(path: Path, packet: QueuePacket, candidates: tuple[CandidateReplica, ...]) -> None:
    payload: dict[str, Any] = {
        "format_version": FANOUT_FORMAT_VERSION,
        "job_id": packet.job_id,
        "archive_sha256": packet.snapshot.archive_sha256,
        "archive_bytes": packet.snapshot.total_bytes,
        "git_head": packet.snapshot.git_head,
        "source_root_name": packet.snapshot.source_root_name,
        "prd_sha256": packet.prd_sha256,
        "prd_bytes": packet.prd_bytes,
        "replication_count": packet.replication_count,
        "claim_retained": True,
        "candidates": [
            {
                "candidate_id": candidate.candidate_id,
                "repository": f"{candidate.candidate_id}/{packet.snapshot.source_root_name}",
                "prd": f"{candidate.candidate_id}/{PRD_FILENAME}",
            }
            for candidate in candidates
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("ascii") + b"\n"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.chmod(temporary, 0o600)
            os.fsync(handle.fileno())
        os.link(temporary, path)
        try:
            _fsync_directory(path.parent)
        except (FanoutError, OSError):
            _unlink_if_same_inode(temporary, path)
            try:
                _fsync_directory(path.parent)
            except (FanoutError, OSError):
                pass
            raise
        published_temporary = temporary
        temporary = None
        try:
            published_temporary.unlink()
        except OSError:
            pass
    except FileExistsError as exc:
        raise FanoutError("candidate manifest already exists") from exc
    except OSError as exc:
        raise FanoutError("candidate manifest cannot be published") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def _unlink_if_same_inode(expected: Path, destination: Path) -> None:
    try:
        expected_stat = expected.stat()
        destination_stat = destination.stat()
        if (
            expected_stat.st_dev == destination_stat.st_dev
            and expected_stat.st_ino == destination_stat.st_ino
        ):
            destination.unlink()
    except (FileNotFoundError, OSError):
        pass


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    except OSError as exc:
        raise FanoutError("candidate directory cannot be synchronized") from exc
    try:
        os.fsync(descriptor)
    except OSError as exc:
        raise FanoutError("candidate directory cannot be synchronized") from exc
    finally:
        os.close(descriptor)
