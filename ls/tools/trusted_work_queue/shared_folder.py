"""Immutable shared-folder transport for trusted full-repository queue packets.

A ready packet is a directory under ``incoming/`` whose final ``packet.json``
marker is published only after a streamed snapshot copy, its adjacent sidecar,
and exact PRD bytes are durable. Claiming moves that directory under ``claims/``
inside the same queue root. The claim remains retained for an external consumer;
this module never extracts, deletes, executes, or contacts a network endpoint.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .snapshot import SnapshotError, SnapshotMetadata, validate_snapshot
except ImportError:  # pragma: no cover - supports direct script execution.
    from snapshot import SnapshotError, SnapshotMetadata, validate_snapshot  # type: ignore

FORMAT_VERSION = 1
INCOMING_DIRECTORY = "incoming"
CLAIMS_DIRECTORY = "claims"
SNAPSHOT_FILENAME = "snapshot.tar.gz"
PRD_FILENAME = "prd.bin"
READY_FILENAME = "packet.json"
CLAIM_SUFFIX = ".claim"
MAX_REPLICATION_COUNT = 64
_COPY_CHUNK_BYTES = 1024 * 1024
_READY_MARKER_MAX_BYTES = 1024
_AT_FDCWD = -100
_RENAME_NOREPLACE = 1
_RENAME_EXCL = 0x00000004
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00$")
_NATIVE_LIBRARY = ctypes.CDLL(None, use_errno=True)


class SharedFolderError(Exception):
    """A queue packet is malformed, unavailable, or cannot be published."""


@dataclass(frozen=True)
class QueuePacket:
    """A verified immutable ready packet stored beneath one queue root."""

    packet_dir: Path
    snapshot: SnapshotMetadata
    prd_sha256: str
    prd_bytes: int
    replication_count: int
    enqueued_at: str

    @property
    def job_id(self) -> str:
        return self.snapshot.job_id

    @property
    def archive_path(self) -> Path:
        return self.packet_dir / SNAPSHOT_FILENAME

    @property
    def manifest_path(self) -> Path:
        return self.archive_path.with_name(self.archive_path.name + ".manifest.json")

    @property
    def prd_path(self) -> Path:
        return self.packet_dir / PRD_FILENAME

    @property
    def ready_path(self) -> Path:
        return self.packet_dir / READY_FILENAME


@dataclass(frozen=True)
class QueueClaim:
    """An exclusive claim retaining its immutable packet for an external consumer."""

    packet: QueuePacket
    claim_marker: Path


def deposit_packet(
    queue_root: str | os.PathLike[str],
    snapshot_archive: str | os.PathLike[str],
    prd_path: str | os.PathLike[str],
    *,
    replication_count: int,
    enqueued_at: datetime | None = None,
) -> QueuePacket:
    """Stream a validated snapshot and verbatim PRD into one immutable packet.

    The source archive is validated before copying and the destination copy is
    validated again before its ready marker is published. The marker is the
    only readiness signal, so incomplete packet directories are never claimed.
    """
    count = _validate_replication_count(replication_count)
    source_archive = _require_regular_file(snapshot_archive, field="snapshot archive")
    source_prd = _require_regular_file(prd_path, field="PRD")
    source_metadata = _validated_snapshot(source_archive)
    root = _prepare_queue_root(queue_root)
    incoming = root / INCOMING_DIRECTORY
    claims = root / CLAIMS_DIRECTORY
    packet_dir = incoming / source_metadata.job_id
    if any(
        os.path.lexists(path)
        for path in (packet_dir, claims / source_metadata.job_id, claims / f"{source_metadata.job_id}{CLAIM_SUFFIX}")
    ):
        raise SharedFolderError("queue packet already exists for this snapshot job")
    stage_dir = incoming / f".{source_metadata.job_id}.{uuid.uuid4().hex}.stage"
    try:
        os.mkdir(stage_dir, 0o700)
        _fsync_directory(incoming)
        archive_destination = stage_dir / SNAPSHOT_FILENAME
        archive_sha256, archive_bytes = _copy_file(source_archive, archive_destination)
        if (
            archive_sha256 != source_metadata.archive_sha256
            or archive_bytes != source_metadata.total_bytes
        ):
            raise SharedFolderError("snapshot changed while being copied into the queue")
        manifest_source = _require_regular_file(
            source_archive.with_name(source_archive.name + ".manifest.json"),
            field="snapshot sidecar",
        )
        _copy_file(manifest_source, archive_destination.with_name(archive_destination.name + ".manifest.json"))
        copied_metadata = _validated_snapshot(archive_destination)
        if copied_metadata != source_metadata:
            raise SharedFolderError("copied snapshot metadata does not match the source snapshot")
        prd_sha256, prd_bytes = _copy_file(source_prd, stage_dir / PRD_FILENAME)
        staged_packet = QueuePacket(
            packet_dir=stage_dir,
            snapshot=copied_metadata,
            prd_sha256=prd_sha256,
            prd_bytes=prd_bytes,
            replication_count=count,
            enqueued_at=_canonical_utc_timestamp(enqueued_at or datetime.now(timezone.utc)),
        )
        _write_ready_marker(staged_packet)
        if any(
            os.path.lexists(path)
            for path in (
                packet_dir,
                claims / source_metadata.job_id,
                claims / f"{source_metadata.job_id}{CLAIM_SUFFIX}",
            )
        ):
            raise SharedFolderError("queue packet already exists for this snapshot job")
        _rename_directory_no_clobber(stage_dir, packet_dir)
        _fsync_directory(incoming)
        return QueuePacket(
            packet_dir=packet_dir,
            snapshot=copied_metadata,
            prd_sha256=prd_sha256,
            prd_bytes=prd_bytes,
            replication_count=count,
            enqueued_at=staged_packet.enqueued_at,
        )
    except SharedFolderError:
        raise
    except OSError as exc:
        raise SharedFolderError("cannot create queue packet") from exc
    finally:
        if stage_dir.exists() or stage_dir.is_symlink():
            shutil.rmtree(stage_dir, ignore_errors=True)


def list_ready_packets(queue_root: str | os.PathLike[str]) -> list[QueuePacket]:
    """Return all verified ready packets ordered by queue time then job id."""
    root = _prepare_queue_root(queue_root)
    incoming = root / INCOMING_DIRECTORY
    packets: list[QueuePacket] = []
    try:
        entries = sorted(incoming.iterdir(), key=lambda entry: entry.name)
    except OSError as exc:
        raise SharedFolderError("cannot inspect queue incoming directory") from exc
    for entry in entries:
        if entry.name.startswith("."):
            continue
        if not _SHA256_RE.fullmatch(entry.name):
            raise SharedFolderError("queue incoming directory contains an invalid packet name")
        if entry.is_symlink():
            raise SharedFolderError("queue incoming directory contains a symbolic link")
        if not entry.is_dir():
            raise SharedFolderError("queue incoming directory contains a non-packet entry")
        ready = entry / READY_FILENAME
        if ready.exists() or ready.is_symlink():
            packets.append(load_packet(entry))
    return sorted(packets, key=lambda packet: (packet.enqueued_at, packet.job_id))


def claim_oldest_packet(queue_root: str | os.PathLike[str]) -> QueueClaim | None:
    """Claim the deterministic oldest ready packet, retaining it under ``claims``.

    A no-clobber marker reserves the oldest job before its directory move. If a
    crashed contender already reserved that oldest ready job, no newer packet is
    claimed; an operator/controller must reconcile that claim first.
    """
    root = _prepare_queue_root(queue_root)
    packets = list_ready_packets(root)
    if not packets:
        return None
    packet = packets[0]
    claims = root / CLAIMS_DIRECTORY
    marker = claims / f"{packet.job_id}{CLAIM_SUFFIX}"
    _write_claim_marker(marker, packet)
    destination = claims / packet.job_id
    try:
        os.rename(packet.packet_dir, destination)
    except FileNotFoundError as exc:
        _unlink_quietly(marker)
        raise SharedFolderError("oldest packet disappeared during claim") from exc
    except OSError as exc:
        raise SharedFolderError("cannot move claimed packet") from exc
    _fsync_directory(packet.packet_dir.parent)
    _fsync_directory(claims)
    claimed_packet = load_packet(destination)
    return QueueClaim(packet=claimed_packet, claim_marker=marker)


def load_packet(packet_dir: str | os.PathLike[str]) -> QueuePacket:
    """Verify a ready or claimed packet without parsing its PRD bytes."""
    directory = Path(packet_dir)
    _require_packet_directory(directory)
    payload = _read_ready_marker(directory / READY_FILENAME)
    expected_fields = {
        "format_version",
        "job_id",
        "archive_sha256",
        "archive_bytes",
        "prd_sha256",
        "prd_bytes",
        "replication_count",
        "enqueued_at",
    }
    if set(payload) != expected_fields:
        raise SharedFolderError("queue ready marker has an unsupported schema")
    if payload["format_version"] != FORMAT_VERSION or not _is_plain_int(payload["format_version"]):
        raise SharedFolderError("queue ready marker version is invalid")
    job_id = _validate_sha256(payload["job_id"], field="job id")
    if directory.name != job_id:
        raise SharedFolderError("queue packet directory name does not match its job id")
    archive = _require_regular_file(directory / SNAPSHOT_FILENAME, field="packet snapshot")
    manifest = _require_regular_file(
        archive.with_name(archive.name + ".manifest.json"),
        field="packet snapshot sidecar",
    )
    metadata = _validated_snapshot(archive, manifest)
    if metadata.job_id != job_id:
        raise SharedFolderError("queue job id does not match the snapshot sidecar")
    if payload["archive_sha256"] != metadata.archive_sha256 or payload["archive_bytes"] != metadata.total_bytes:
        raise SharedFolderError("queue ready marker does not match the snapshot sidecar")
    prd_sha256, prd_bytes = _hash_file(_require_regular_file(directory / PRD_FILENAME, field="packet PRD"))
    if payload["prd_sha256"] != prd_sha256 or payload["prd_bytes"] != prd_bytes:
        raise SharedFolderError("queue ready marker does not match PRD bytes")
    return QueuePacket(
        packet_dir=directory,
        snapshot=metadata,
        prd_sha256=prd_sha256,
        prd_bytes=prd_bytes,
        replication_count=_validate_replication_count(payload["replication_count"]),
        enqueued_at=_parse_utc_timestamp(payload["enqueued_at"]),
    )


def _validated_snapshot(
    archive: Path, manifest: Path | None = None
) -> SnapshotMetadata:
    try:
        return validate_snapshot(archive, manifest)
    except SnapshotError as exc:
        raise SharedFolderError("snapshot validation failed") from exc


def _prepare_queue_root(value: str | os.PathLike[str]) -> Path:
    root = Path(value).expanduser()
    try:
        _require_directory(root, field="queue root", create=True)
        os.chmod(root, 0o700)
        for name in (INCOMING_DIRECTORY, CLAIMS_DIRECTORY):
            directory = root / name
            _require_directory(directory, field=f"queue {name} directory", create=True)
            os.chmod(directory, 0o700)
        _fsync_directory(root)
    except OSError as exc:
        raise SharedFolderError("cannot prepare shared queue root") from exc
    return root


def _require_regular_file(value: str | os.PathLike[str], *, field: str) -> Path:
    path = Path(value).expanduser()
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise SharedFolderError(f"{field} cannot be inspected") from exc
    if not stat.S_ISREG(mode):
        raise SharedFolderError(f"{field} must be a regular non-symlink file")
    return path


def _require_packet_directory(path: Path) -> None:
    _require_directory(path, field="queue packet directory", create=False)


def _require_directory(path: Path, *, field: str, create: bool) -> None:
    try:
        if create and not os.path.lexists(path):
            path.mkdir(parents=True, exist_ok=False)
        mode = path.lstat().st_mode
    except OSError as exc:
        raise SharedFolderError(f"{field} cannot be inspected") from exc
    if not stat.S_ISDIR(mode):
        raise SharedFolderError(f"{field} must be a non-symlink directory")


def _copy_file(source: Path, destination: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    descriptor: int | None = None
    try:
        with source.open("rb") as reader:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            flags |= getattr(os, "O_CLOEXEC", 0)
            descriptor = os.open(destination, flags, 0o600)
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb", closefd=True) as writer:
                descriptor = None
                while chunk := reader.read(_COPY_CHUNK_BYTES):
                    digest.update(chunk)
                    total += len(chunk)
                    writer.write(chunk)
                writer.flush()
                os.fsync(writer.fileno())
        _fsync_directory(destination.parent)
    except FileExistsError as exc:
        raise SharedFolderError("queue packet member already exists") from exc
    except OSError as exc:
        raise SharedFolderError("cannot stream queue packet member") from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
    return digest.hexdigest(), total


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(_COPY_CHUNK_BYTES):
                digest.update(chunk)
                total += len(chunk)
    except OSError as exc:
        raise SharedFolderError("cannot read queue packet member") from exc
    return digest.hexdigest(), total


def _write_ready_marker(packet: QueuePacket) -> None:
    payload = {
        "format_version": FORMAT_VERSION,
        "job_id": packet.job_id,
        "archive_sha256": packet.snapshot.archive_sha256,
        "archive_bytes": packet.snapshot.total_bytes,
        "prd_sha256": packet.prd_sha256,
        "prd_bytes": packet.prd_bytes,
        "replication_count": packet.replication_count,
        "enqueued_at": packet.enqueued_at,
    }
    _write_json_no_clobber(packet.ready_path, payload, description="queue ready marker")


def _write_claim_marker(marker: Path, packet: QueuePacket) -> None:
    payload = {"format_version": FORMAT_VERSION, "job_id": packet.job_id}
    _write_json_no_clobber(marker, payload, description="queue claim marker")


def _write_json_no_clobber(path: Path, payload: dict[str, Any], *, description: str) -> None:
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("ascii") + b"\n"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.link(temporary, path)
        temporary.unlink()
        temporary = None
        _fsync_directory(path.parent)
    except FileExistsError as exc:
        raise SharedFolderError(f"{description} already exists") from exc
    except OSError as exc:
        raise SharedFolderError(f"cannot publish {description}") from exc
    finally:
        if temporary is not None:
            _unlink_quietly(temporary)


def _rename_directory_no_clobber(source: Path, destination: Path) -> None:
    if sys.platform.startswith("linux"):
        function = getattr(_NATIVE_LIBRARY, "renameat2", None)
        if function is None:
            raise SharedFolderError("atomic no-clobber queue publication is unavailable")
        function.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        function.restype = ctypes.c_int
        result = function(
            _AT_FDCWD,
            os.fsencode(source),
            _AT_FDCWD,
            os.fsencode(destination),
            _RENAME_NOREPLACE,
        )
    elif sys.platform == "darwin":
        function = getattr(_NATIVE_LIBRARY, "renamex_np", None)
        if function is None:
            raise SharedFolderError("atomic no-clobber queue publication is unavailable")
        function.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        function.restype = ctypes.c_int
        result = function(os.fsencode(source), os.fsencode(destination), _RENAME_EXCL)
    else:
        raise SharedFolderError("atomic no-clobber queue publication is unavailable")
    if result == 0:
        return
    error = ctypes.get_errno()
    if error in (errno.EEXIST, errno.ENOTEMPTY):
        raise SharedFolderError("queue packet already exists for this snapshot job")
    raise SharedFolderError("cannot publish queue packet") from OSError(
        error,
        os.strerror(error),
        destination,
    )


def _read_ready_marker(path: Path) -> dict[str, Any]:
    descriptor: int | None = None
    try:
        try:
            initial_stat = path.lstat()
        except OSError as exc:
            raise SharedFolderError("queue ready marker cannot be inspected") from exc
        if not stat.S_ISREG(initial_stat.st_mode):
            raise SharedFolderError("queue ready marker must be a regular non-symlink file")
        if initial_stat.st_size > _READY_MARKER_MAX_BYTES:
            raise SharedFolderError("queue ready marker is too large")

        nofollow = getattr(os, "O_NOFOLLOW", None)
        nonblock = getattr(os, "O_NONBLOCK", None)
        if nofollow is None or nonblock is None:
            raise SharedFolderError("queue ready marker cannot be opened safely")
        flags = os.O_RDONLY | nofollow | nonblock
        flags |= getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise SharedFolderError("queue ready marker cannot be opened") from exc

        try:
            descriptor_stat = os.fstat(descriptor)
        except OSError as exc:
            raise SharedFolderError("queue ready marker cannot be inspected") from exc
        identity = (initial_stat.st_dev, initial_stat.st_ino)
        if (
            not stat.S_ISREG(descriptor_stat.st_mode)
            or (descriptor_stat.st_dev, descriptor_stat.st_ino) != identity
            or descriptor_stat.st_size > _READY_MARKER_MAX_BYTES
        ):
            raise SharedFolderError("queue ready marker is not a bounded regular file")

        data = bytearray()
        while True:
            remaining = _READY_MARKER_MAX_BYTES + 1 - len(data)
            if remaining <= 0:
                raise SharedFolderError("queue ready marker is too large")
            try:
                chunk = os.read(descriptor, min(64 * 1024, remaining))
            except OSError as exc:
                raise SharedFolderError("queue ready marker cannot be read") from exc
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > _READY_MARKER_MAX_BYTES:
                raise SharedFolderError("queue ready marker is too large")

        try:
            finished_stat = os.fstat(descriptor)
        except OSError as exc:
            raise SharedFolderError("queue ready marker cannot be inspected") from exc
        if (
            not stat.S_ISREG(finished_stat.st_mode)
            or (finished_stat.st_dev, finished_stat.st_ino) != identity
            or finished_stat.st_size > _READY_MARKER_MAX_BYTES
            or len(data) != finished_stat.st_size
        ):
            raise SharedFolderError("queue ready marker changed while being read")

        try:
            final_stat = path.lstat()
        except OSError as exc:
            raise SharedFolderError("queue ready marker cannot be inspected") from exc
        if (
            not stat.S_ISREG(final_stat.st_mode)
            or (final_stat.st_dev, final_stat.st_ino) != identity
            or final_stat.st_size != finished_stat.st_size
        ):
            raise SharedFolderError("queue ready marker changed while being read")
        loaded = json.loads(data.decode("utf-8"))
    except SharedFolderError:
        raise
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise SharedFolderError("queue ready marker cannot be read") from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError as exc:
                raise SharedFolderError("queue ready marker descriptor cannot be closed") from exc
    if not isinstance(loaded, dict):
        raise SharedFolderError("queue ready marker must be a JSON object")
    return loaded


def _validate_replication_count(value: object) -> int:
    if not _is_plain_int(value) or not 1 <= value <= MAX_REPLICATION_COUNT:
        raise SharedFolderError(f"replication count must be an integer from 1 to {MAX_REPLICATION_COUNT}")
    return value


def _validate_sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise SharedFolderError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _canonical_utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise SharedFolderError("queue timestamp must include a timezone")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _parse_utc_timestamp(value: object) -> str:
    if not isinstance(value, str) or not _UTC_TIMESTAMP_RE.fullmatch(value):
        raise SharedFolderError("queue timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise SharedFolderError("queue timestamp is invalid") from exc
    canonical = _canonical_utc_timestamp(parsed)
    if canonical != value:
        raise SharedFolderError("queue timestamp is invalid")
    return canonical


def _is_plain_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    except OSError as exc:
        raise SharedFolderError("cannot open queue directory for sync") from exc
    try:
        os.fsync(descriptor)
    except OSError as exc:
        raise SharedFolderError("cannot sync queue directory") from exc
    finally:
        os.close(descriptor)


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass
