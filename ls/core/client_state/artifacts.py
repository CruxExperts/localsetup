from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import time
from typing import Iterable

from .locator import refresh_state_location
from .models import ClientStateError, StateLocation


_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_EXTENSION = re.compile(r"[a-z0-9]{1,10}")
_STAMP = re.compile(r"[0-9]{8}T[0-9]{9}Z")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
_MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
_MAX_METADATA_BYTES = 1024 * 1024
_MAX_PENDING_RECEIPTS = 100
_MAX_RELATIVE_PATH_LENGTH = 512
_PENDING_PREFIX = ".localsetup-pending-"
_PENDING_SUFFIX = ".json"
_ALLOCATION_LOCK = ".localsetup-artifacts.lock"
_ALLOCATION_LOCK_TIMEOUT_SECONDS = 0.5
_ALLOCATION_LOCK_POLL_SECONDS = 0.01


@dataclass(frozen=True)
class ParsedArtifactName:
    agent: str
    created_at: str
    purpose: str
    collision: int
    extension: str


@dataclass(frozen=True)
class ArtifactRequest:
    content: bytes
    purpose: str
    extension: str
    kind: str
    schema: str
    producer: str
    agent: str
    predecessor: str | None
    checkpoint: str | None
    consumers: tuple[str, ...]
    created_at: str
    metadata_schema: dict


@dataclass(frozen=True)
class OwnedEntry:
    name: str
    device: int
    inode: int
    changed_ns: int
    sha256: str


def _slug(value: str, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not (1 <= len(value) <= maximum) or not _SLUG.fullmatch(value):
        raise ClientStateError(
            f"{label} must be lowercase kebab-case and at most {maximum} characters",
            code=f"invalid_{label}",
        )
    return value


def _validate_content(content: bytes) -> bytes:
    if not isinstance(content, bytes):
        raise ClientStateError("artifact content must be bytes", code="invalid_content")
    if len(content) > _MAX_ARTIFACT_BYTES:
        raise ClientStateError("artifact content exceeds the supported size limit", code="invalid_content")
    return content


def _relative(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ClientStateError(
            f"{label} must be a normalized POSIX-relative path", code=f"invalid_{label}"
        )
    if (
        not value
        or len(value) > _MAX_RELATIVE_PATH_LENGTH
        or "\\" in value
        or ":" in value
        or value.startswith("/")
        or "//" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ClientStateError(f"{label} must be a normalized POSIX-relative path", code=f"invalid_{label}")
    path = PurePosixPath(value)
    if not path.parts or any(part in {"", ".", ".."} for part in path.parts) or path.as_posix() != value:
        raise ClientStateError(f"{label} must be a normalized POSIX-relative path", code=f"invalid_{label}")
    return value


def _metadata_payload(
    location: StateLocation, request: ArtifactRequest, artifact_name: str
) -> tuple[dict, bytes]:
    metadata = {
        "schema_version": 1,
        "artifact": artifact_name,
        "checkpoint": request.checkpoint,
        "client": {
            "key": location.client,
            "scope": location.scope,
            "registry_schema_version": location.registry_schema_version,
            "variant_digest": location.variant_digest,
        },
        "consumers": list(request.consumers),
        "content": {
            "sha256": hashlib.sha256(request.content).hexdigest(),
            "size": len(request.content),
        },
        "created_at": request.created_at,
        "format": request.extension,
        "kind": request.kind,
        "predecessor": request.predecessor,
        "producer": request.producer,
        "schema": request.schema,
    }
    if location.git:
        metadata["repository"] = {
            "head": location.git.head,
            "ref": location.git.ref,
            "root": ".",
        }
    for metadata_schema in _request_schemas(request):
        if _schema_issues(metadata, metadata_schema):
            raise ClientStateError("artifact metadata failed schema validation", code="invalid_metadata")
    encoded = (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if len(encoded) > _MAX_METADATA_BYTES:
        raise ClientStateError(
            "artifact metadata exceeds the supported size limit", code="invalid_metadata"
        )
    return metadata, encoded


def preflight_artifact_request(location: StateLocation, request: ArtifactRequest) -> None:
    _validate_artifact_request(request)
    current = refresh_state_location(location, allow_created_roots=True)
    collision_safe_name = (
        f"{request.agent}-{request.created_at}-{request.purpose}-99.{request.extension}"
    )
    parse_artifact_name(collision_safe_name)
    _metadata_payload(current, request, collision_safe_name)


def _timestamp(now: datetime) -> str:
    if now.tzinfo is None:
        raise ClientStateError("artifact clock must be timezone-aware", code="invalid_timestamp")
    utc = now.astimezone(timezone.utc)
    return utc.strftime("%Y%m%dT%H%M%S") + f"{utc.microsecond // 1000:03d}Z"


def _validate_timestamp(value: str) -> None:
    if not isinstance(value, str) or not _STAMP.fullmatch(value):
        raise ClientStateError("artifact timestamp is malformed", code="invalid_artifact_name")
    try:
        datetime.strptime(value[:15] + value[15:18] + "000Z", "%Y%m%dT%H%M%S%fZ")
    except ValueError as exc:
        raise ClientStateError("artifact timestamp is not a real UTC time", code="invalid_artifact_name") from exc


def parse_artifact_name(value: str) -> ParsedArtifactName:
    if "/" in value or "\\" in value or any(ord(character) < 32 for character in value):
        raise ClientStateError("artifact filename is malformed", code="invalid_artifact_name")
    marker = re.search(r"-([0-9]{8}T[0-9]{9}Z)-", value)
    if marker is None or value.count(marker.group(0)) != 1:
        raise ClientStateError("artifact filename is malformed", code="invalid_artifact_name")
    agent = value[: marker.start()]
    created_at = marker.group(1)
    tail = value[marker.end() :]
    if "." not in tail:
        raise ClientStateError("artifact filename is malformed", code="invalid_artifact_name")
    purpose_with_collision, extension = tail.rsplit(".", 1)
    collision = 0
    collision_match = re.search(r"-([0-9]{2})$", purpose_with_collision)
    if collision_match:
        collision = int(collision_match.group(1))
        if collision == 0:
            raise ClientStateError("artifact collision suffix must be -01 through -99", code="invalid_artifact_name")
        purpose = purpose_with_collision[: collision_match.start()]
    else:
        purpose = purpose_with_collision
    _slug(agent, "agent", 48)
    _slug(purpose, "purpose", 64)
    if not _EXTENSION.fullmatch(extension):
        raise ClientStateError("artifact extension is invalid", code="invalid_artifact_name")
    _validate_timestamp(created_at)
    canonical = f"{agent}-{created_at}-{purpose}{f'-{collision:02d}' if collision else ''}.{extension}"
    if canonical != value:
        raise ClientStateError("artifact filename is not canonical", code="invalid_artifact_name")
    return ParsedArtifactName(agent, created_at, purpose, collision, extension)


def _load_schema_file(path: Path) -> dict:
    try:
        fd = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as exc:
        raise ClientStateError("artifact metadata schema is unavailable", code="invalid_metadata_schema") from exc
    try:
        result = os.fstat(fd)
        if not stat.S_ISREG(result.st_mode) or result.st_mode & 0o444 == 0 or result.st_size > _MAX_METADATA_BYTES:
            raise ClientStateError("artifact metadata schema must be a readable regular file", code="invalid_metadata_schema")
        chunks: list[bytes] = []
        while chunk := os.read(fd, 64 * 1024):
            chunks.append(chunk)
        try:
            payload = json.loads(b"".join(chunks).decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ClientStateError("artifact metadata schema is unreadable or invalid", code="invalid_metadata_schema") from exc
    finally:
        os.close(fd)
    if not isinstance(payload, dict):
        raise ClientStateError("artifact metadata schema must be a JSON object", code="invalid_metadata_schema")
    return payload


def _schema_issues(payload: dict, schema: dict) -> list[str]:
    try:
        from jsonschema import Draft202012Validator, exceptions
    except ImportError as exc:
        raise ClientStateError("JSON schema validation is unavailable", code="invalid_metadata_schema") from exc
    try:
        Draft202012Validator.check_schema(schema)
    except exceptions.SchemaError as exc:
        raise ClientStateError("artifact metadata schema is invalid", code="invalid_metadata_schema") from exc
    return [error.message for error in sorted(Draft202012Validator(schema).iter_errors(payload), key=lambda item: list(item.path))]


def _official_schema_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "client-state-artifact.schema.json"


def _request_schemas(request: ArtifactRequest) -> tuple[dict, ...]:
    if not isinstance(request.metadata_schema, dict):
        raise ClientStateError("artifact metadata schema must be a JSON object", code="invalid_metadata_schema")
    official = _load_schema_file(_official_schema_path())
    _schema_issues({}, official)
    _schema_issues({}, request.metadata_schema)
    return (official,) if request.metadata_schema == official else (official, request.metadata_schema)


def _validate_artifact_request(request: ArtifactRequest) -> ArtifactRequest:
    if not isinstance(request, ArtifactRequest):
        raise ClientStateError("prepared artifact request is invalid", code="invalid_metadata")
    _validate_content(request.content)
    _slug(request.agent, "agent", 48)
    _slug(request.purpose, "purpose", 64)
    if re.search(r"-[0-9]{2}$", request.purpose):
        raise ClientStateError("purpose must not end in a collision suffix", code="invalid_purpose")
    if not isinstance(request.extension, str) or not _EXTENSION.fullmatch(request.extension):
        raise ClientStateError(
            "extension must be 1-10 lowercase alphanumeric characters", code="invalid_extension"
        )
    _slug(request.kind, "kind", 32)
    _slug(request.schema, "schema", 64)
    _slug(request.producer, "producer", 64)
    _relative(request.predecessor, "predecessor")
    _relative(request.checkpoint, "checkpoint")
    if not isinstance(request.consumers, tuple):
        raise ClientStateError("consumers must be a canonical sorted tuple", code="invalid_consumer")
    canonical_consumers = tuple(sorted({_slug(item, "consumer", 64) for item in request.consumers}))
    if request.consumers != canonical_consumers:
        raise ClientStateError("consumers must be sorted and unique", code="invalid_consumer")
    _validate_timestamp(request.created_at)
    _request_schemas(request)
    return request


def prepare_artifact_request(
    location: StateLocation,
    *,
    content: bytes,
    purpose: str,
    extension: str,
    kind: str,
    schema: str,
    producer: str,
    agent: str | None = None,
    predecessor: str | None = None,
    checkpoint: str | None = None,
    consumers: Iterable[str] = (),
    now: datetime | None = None,
    metadata_schema: Path | None = None,
) -> ArtifactRequest:
    content = _validate_content(content)
    if isinstance(consumers, (str, bytes)):
        raise ClientStateError("consumers must be an iterable of slugs", code="invalid_consumer")
    resolved_agent = _slug(
        location.client.split("/", 1)[1] if agent is None else agent, "agent", 48
    )
    purpose = _slug(purpose, "purpose", 64)
    if re.search(r"-[0-9]{2}$", purpose):
        raise ClientStateError("purpose must not end in a collision suffix", code="invalid_purpose")
    if not _EXTENSION.fullmatch(extension):
        raise ClientStateError("extension must be 1-10 lowercase alphanumeric characters", code="invalid_extension")
    schema_path = metadata_schema or _official_schema_path()
    schema_payload = _load_schema_file(schema_path)
    request = ArtifactRequest(
        content=content,
        purpose=purpose,
        extension=extension,
        kind=_slug(kind, "kind", 32),
        schema=_slug(schema, "schema", 64),
        producer=_slug(producer, "producer", 64),
        agent=resolved_agent,
        predecessor=_relative(predecessor, "predecessor"),
        checkpoint=_relative(checkpoint, "checkpoint"),
        consumers=tuple(sorted({_slug(item, "consumer", 64) for item in consumers})),
        created_at=_timestamp(now or datetime.now(timezone.utc)),
        metadata_schema=schema_payload,
    )
    _validate_artifact_request(request)
    collision_safe_name = f"{request.agent}-{request.created_at}-{request.purpose}-99.{request.extension}"
    parse_artifact_name(collision_safe_name)
    _metadata_payload(location, request, collision_safe_name)
    return request


def _is_managed_global_component(path: Path, owner_root: Path | None) -> bool:
    if owner_root is None:
        return False
    try:
        path.relative_to(owner_root)
    except ValueError:
        return False
    return True


def _nearest_existing_pre_owner(owner_root: Path) -> Path | None:
    current = owner_root
    while True:
        try:
            current.stat(follow_symlinks=False)
        except FileNotFoundError:
            parent = current.parent
            if parent == current:
                raise ClientStateError(
                    "global client state ownership boundary is unavailable",
                    code="unsafe_state_path",
                )
            current = parent
            continue
        except OSError as exc:
            raise ClientStateError(
                "global client state ownership boundary is unavailable",
                code="unsafe_state_path",
            ) from exc
        return None if current == owner_root else current


def _created_directory(parent_fd: int, name: str) -> int:
    os.mkdir(name, 0o700, dir_fd=parent_fd)
    child_fd: int | None = None
    try:
        os.chmod(name, 0o700, dir_fd=parent_fd, follow_symlinks=False)
        child_fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
        os.fchmod(child_fd, 0o700)
        details = os.fstat(child_fd)
        if not stat.S_ISDIR(details.st_mode) or details.st_uid != os.geteuid():
            raise ClientStateError("new client state directory is unsafe", code="unsafe_state_path")
        os.fsync(child_fd)
        os.fsync(parent_fd)
        return child_fd
    except Exception as exc:
        if child_fd is not None:
            os.close(child_fd)
        raise ClientStateError(
            "client state directory creation durability is ambiguous",
            code="artifact_commit_ambiguous",
        ) from exc
    except BaseException:
        if child_fd is not None:
            os.close(child_fd)
        raise


def _open_absolute_directory(
    path: Path,
    *,
    create: bool,
    owner_root: Path | None = None,
    pre_owner_root: Path | None = None,
) -> int:
    if not path.is_absolute():
        raise ClientStateError("client state path is not absolute", code="unsafe_state_path")
    if pre_owner_root is not None:
        if owner_root is None or not pre_owner_root.is_absolute():
            raise ClientStateError("global ownership boundary is invalid", code="unsafe_state_path")
        try:
            owner_root.relative_to(pre_owner_root)
        except ValueError as exc:
            raise ClientStateError("global ownership boundary is invalid", code="unsafe_state_path") from exc
    fd = os.open("/", _DIRECTORY_FLAGS)
    current = Path(path.anchor)
    try:
        if current == pre_owner_root and os.fstat(fd).st_uid not in {0, os.geteuid()}:
            raise ClientStateError(
                "global client state ancestor has an unexpected owner",
                code="unsafe_state_path",
            )
        for part in path.parts[1:]:
            current /= part
            try:
                next_fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                if current == pre_owner_root:
                    raise ClientStateError(
                        "global ownership boundary changed during traversal",
                        code="unsafe_state_path",
                    )
                try:
                    next_fd = _created_directory(fd, part)
                except FileExistsError:
                    next_fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=fd)
            details = os.fstat(next_fd)
            if current == pre_owner_root and details.st_uid not in {0, os.geteuid()}:
                os.close(next_fd)
                raise ClientStateError(
                    "global client state ancestor has an unexpected owner",
                    code="unsafe_state_path",
                )
            if _is_managed_global_component(current, owner_root) and details.st_uid != os.geteuid():
                os.close(next_fd)
                raise ClientStateError(
                    "global client state path has an unexpected owner", code="unsafe_state_path"
                )
            os.close(fd)
            fd = next_fd
        details = os.fstat(fd)
        if details.st_uid != os.geteuid():
            raise ClientStateError("client state root has an unexpected owner", code="unsafe_state_path")
        os.fchmod(fd, 0o700)
        return fd
    except Exception:
        os.close(fd)
        raise


def _exclusive_write(directory_fd: int, name: str, data: bytes) -> OwnedEntry:
    flags = os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(name, flags, 0o600, dir_fd=directory_fd)
    closed = False
    offset = 0
    try:
        os.fchmod(fd, 0o600)
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode) or details.st_uid != os.geteuid() or details.st_nlink != 1:
            raise ClientStateError("new artifact entry is unsafe", code="unsafe_state_path")
        while offset < len(data):
            written = os.write(fd, data[offset:])
            if written <= 0:
                raise ClientStateError("artifact write was incomplete", code="artifact_write_failed")
            offset += written
        os.fsync(fd)
        details = os.fstat(fd)
        return OwnedEntry(
            name, details.st_dev, details.st_ino, details.st_ctime_ns,
            hashlib.sha256(data).hexdigest(),
        )
    except BaseException:
        details = os.fstat(fd)
        os.close(fd)
        closed = True
        partial = OwnedEntry(
            name, details.st_dev, details.st_ino, details.st_ctime_ns,
            hashlib.sha256(data[:offset]).hexdigest(),
        )
        try:
            _unlink_owned(directory_fd, partial)
        except ClientStateError as exc:
            raise ClientStateError("artifact write cleanup is ambiguous", code="artifact_commit_ambiguous") from exc
        raise
    finally:
        if not closed:
            os.close(fd)


def _owned_entry(directory_fd: int, name: str, *, maximum: int) -> OwnedEntry:
    data, details = _read_regular_with_identity(directory_fd, name, maximum=maximum)
    return OwnedEntry(
        name, details.st_dev, details.st_ino, details.st_ctime_ns,
        hashlib.sha256(data).hexdigest(),
    )


def _assert_owned(directory_fd: int, entry: OwnedEntry, *, maximum: int = _MAX_ARTIFACT_BYTES) -> None:
    try:
        current = _owned_entry(directory_fd, entry.name, maximum=maximum)
    except FileNotFoundError as exc:
        raise ClientStateError("owned artifact entry disappeared", code="artifact_commit_ambiguous") from exc
    if current != entry:
        raise ClientStateError("owned artifact entry changed", code="artifact_commit_ambiguous")


def _unlink_owned(directory_fd: int, entry: OwnedEntry, *, maximum: int = _MAX_ARTIFACT_BYTES) -> None:
    _assert_owned(directory_fd, entry, maximum=maximum)
    os.unlink(entry.name, dir_fd=directory_fd)


def _pending_name(artifact_name: str) -> str:
    return f"{_PENDING_PREFIX}{artifact_name}{_PENDING_SUFFIX}"


def _pending_payload(artifact_name: str, metadata_name: str, content: bytes, metadata: bytes) -> bytes:
    payload = {
        "artifact": artifact_name,
        "artifact_sha256": hashlib.sha256(content).hexdigest(),
        "metadata": metadata_name,
        "metadata_sha256": hashlib.sha256(metadata).hexdigest(),
        "schema_version": 1,
    }
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _cleanup_created(directory_fd: int, entries: Iterable[OwnedEntry], *, ambiguous_message: str) -> None:
    try:
        owned = tuple(entries)
        for entry in owned:
            _assert_owned(directory_fd, entry)
        for entry in owned:
            _unlink_owned(directory_fd, entry)
        os.fsync(directory_fd)
    except (OSError, ClientStateError) as exc:
        raise ClientStateError(ambiguous_message, code="artifact_commit_ambiguous") from exc


def _recover_pending(directory_fd: int) -> None:
    pending: list[str] = []
    with os.scandir(directory_fd) as entries:
        for item in entries:
            if item.name.startswith(_PENDING_PREFIX) and item.name.endswith(_PENDING_SUFFIX):
                pending.append(item.name)
                if len(pending) > _MAX_PENDING_RECEIPTS:
                    raise ClientStateError(
                        "too many pending artifact allocations require recovery", code="artifact_recovery_required"
                    )
    pending.sort()
    changed = False
    for receipt_name in pending:
        try:
            encoded, receipt_details = _read_regular_with_identity(
                directory_fd, receipt_name, maximum=_MAX_METADATA_BYTES
            )
            receipt = json.loads(encoded.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError, ClientStateError) as exc:
            raise ClientStateError("pending artifact allocation is unreadable", code="artifact_recovery_required") from exc
        if not isinstance(receipt, dict) or set(receipt) != {
            "artifact", "artifact_sha256", "metadata", "metadata_sha256", "schema_version"
        } or receipt.get("schema_version") != 1:
            raise ClientStateError("pending artifact allocation is invalid", code="artifact_recovery_required")
        artifact_name = str(receipt["artifact"])
        metadata_name = str(receipt["metadata"])
        if _pending_name(artifact_name) != receipt_name or metadata_name != f"{artifact_name}.meta.json":
            raise ClientStateError("pending artifact allocation is invalid", code="artifact_recovery_required")
        parse_artifact_name(artifact_name)
        receipt_entry = OwnedEntry(
            receipt_name,
            receipt_details.st_dev,
            receipt_details.st_ino,
            receipt_details.st_ctime_ns,
            hashlib.sha256(encoded).hexdigest(),
        )
        try:
            artifact_entry = _owned_entry(directory_fd, artifact_name, maximum=_MAX_ARTIFACT_BYTES)
        except FileNotFoundError:
            artifact_entry = None
        try:
            metadata_entry = _owned_entry(directory_fd, metadata_name, maximum=_MAX_METADATA_BYTES)
        except FileNotFoundError:
            metadata_entry = None
        artifact_digest = artifact_entry.sha256 if artifact_entry else None
        metadata_digest = metadata_entry.sha256 if metadata_entry else None
        expected_artifact = str(receipt["artifact_sha256"])
        expected_metadata = str(receipt["metadata_sha256"])
        for digest in (expected_artifact, expected_metadata):
            if not _SHA256.fullmatch(digest):
                raise ClientStateError("pending artifact allocation is invalid", code="artifact_recovery_required")
        if artifact_digest not in {None, expected_artifact} or metadata_digest not in {None, expected_metadata}:
            raise ClientStateError("pending allocation collides with foreign state", code="artifact_recovery_required")
        if artifact_digest is None or metadata_digest is None:
            if artifact_digest is not None:
                assert artifact_entry is not None
                _unlink_owned(directory_fd, artifact_entry, maximum=_MAX_ARTIFACT_BYTES)
            if metadata_digest is not None:
                assert metadata_entry is not None
                _unlink_owned(directory_fd, metadata_entry)
        _unlink_owned(directory_fd, receipt_entry)
        changed = True
    if changed:
        try:
            os.fsync(directory_fd)
        except OSError as exc:
            raise ClientStateError("artifact recovery durability is ambiguous", code="artifact_commit_ambiguous") from exc


def _read_regular_with_identity(directory_fd: int, name: str, *, maximum: int) -> tuple[bytes, os.stat_result]:
    before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid() or before.st_nlink != 1:
        raise ClientStateError("artifact entry is not an owned regular file", code="invalid_artifact")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(name, flags, dir_fd=directory_fd)
    try:
        details = os.fstat(fd)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_uid != os.geteuid()
            or details.st_nlink != 1
            or (details.st_dev, details.st_ino) != (before.st_dev, before.st_ino)
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_size > maximum
        ):
            raise ClientStateError("artifact entry is not a regular file", code="invalid_artifact")
        chunks: list[bytes] = []
        total = 0
        while chunk := os.read(fd, 1024 * 1024):
            total += len(chunk)
            if total > maximum:
                raise ClientStateError("artifact entry exceeds its size limit", code="invalid_artifact")
            chunks.append(chunk)
        return b"".join(chunks), details
    finally:
        os.close(fd)


def _read_regular(directory_fd: int, name: str, *, maximum: int) -> bytes:
    return _read_regular_with_identity(directory_fd, name, maximum=maximum)[0]


def _open_owned_lock(directory_fd: int, name: str) -> int:
    try:
        before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        try:
            fd = os.open(
                name,
                os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=directory_fd,
            )
            before = os.fstat(fd)
        except FileExistsError:
            before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            fd = os.open(name, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
    else:
        fd = os.open(name, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
    details = os.fstat(fd)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_uid != os.geteuid()
        or before.st_nlink != 1
        or not stat.S_ISREG(details.st_mode)
        or details.st_uid != os.geteuid()
        or details.st_nlink != 1
        or (before.st_dev, before.st_ino) != (details.st_dev, details.st_ino)
    ):
        os.close(fd)
        raise ClientStateError("artifact allocation lock is unsafe", code="artifact_locked")
    os.fchmod(fd, 0o600)
    return fd


def _acquire_allocation_lock(
    lock_fd: int,
    *,
    timeout: float = _ALLOCATION_LOCK_TIMEOUT_SECONDS,
    poll: float = _ALLOCATION_LOCK_POLL_SECONDS,
) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError as exc:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ClientStateError(
                    "artifact allocation lock wait timed out", code="artifact_locked"
                ) from exc
            time.sleep(min(poll, remaining))
        except OSError as exc:
            raise ClientStateError(
                "artifact allocation lock is unavailable", code="artifact_locked"
            ) from exc


def _bound_location(location: StateLocation, directory_fd: int) -> StateLocation:
    current = refresh_state_location(location, allow_created_roots=True)
    identity = os.fstat(directory_fd)
    if current.root_identity != (identity.st_dev, identity.st_ino):
        raise ClientStateError("client state root changed during operation", code="stale_state_binding")
    return current


def _open_location_directory(location: StateLocation, *, create: bool) -> int:
    if location.scope == "global":
        if location.owner_root is None:
            raise ClientStateError("global client state owner is unavailable", code="unsafe_state_path")
        pre_owner_root = _nearest_existing_pre_owner(location.owner_root)
        return _open_absolute_directory(
            location.root,
            create=create,
            owner_root=location.owner_root,
            pre_owner_root=pre_owner_root,
        )
    return _open_absolute_directory(location.root, create=create)


def allocate_artifact(location: StateLocation, *, prepared: ArtifactRequest | None = None, **kwargs) -> dict:
    request = prepared or prepare_artifact_request(location, **kwargs)
    preflight_artifact_request(location, request)
    refresh_state_location(location, allow_created_roots=True)
    try:
        directory_fd = _open_location_directory(location, create=True)
    except OSError as exc:
        raise ClientStateError("client state root is unsafe or unavailable", code="unsafe_state_path") from exc
    lock_fd: int | None = None
    try:
        current = _bound_location(location, directory_fd)
        try:
            lock_fd = _open_owned_lock(directory_fd, _ALLOCATION_LOCK)
            _acquire_allocation_lock(lock_fd)
        except OSError as exc:
            raise ClientStateError("artifact allocation lock is unavailable", code="artifact_locked") from exc
        current = _bound_location(location, directory_fd)
        _recover_pending(directory_fd)
        base = f"{request.agent}-{request.created_at}-{request.purpose}"
        for collision in range(100):
            suffix = "" if collision == 0 else f"-{collision:02d}"
            name = f"{base}{suffix}.{request.extension}"
            parse_artifact_name(name)
            metadata_name = f"{name}.meta.json"
            metadata, encoded = _metadata_payload(current, request, name)
            pending_name = _pending_name(name)
            pending = _pending_payload(name, metadata_name, request.content, encoded)
            try:
                pending_entry = _exclusive_write(directory_fd, pending_name, pending)
            except FileExistsError:
                _recover_pending(directory_fd)
                continue
            try:
                os.fsync(directory_fd)
            except OSError:
                _cleanup_created(
                    directory_fd,
                    (pending_entry,),
                    ambiguous_message="pending allocation durability is ambiguous",
                )
                raise ClientStateError(
                    "pending allocation was not durable", code="artifact_commit_ambiguous"
                )
            try:
                artifact_entry = _exclusive_write(directory_fd, name, request.content)
            except FileExistsError:
                _cleanup_created(
                    directory_fd, (pending_entry,), ambiguous_message="artifact collision cleanup is ambiguous"
                )
                continue
            except BaseException:
                _cleanup_created(
                    directory_fd, (pending_entry,), ambiguous_message="artifact cleanup is ambiguous"
                )
                raise
            try:
                metadata_entry = _exclusive_write(directory_fd, metadata_name, encoded)
            except FileExistsError:
                _cleanup_created(
                    directory_fd,
                    (artifact_entry, pending_entry),
                    ambiguous_message="artifact collision cleanup is ambiguous",
                )
                continue
            except BaseException:
                _cleanup_created(
                    directory_fd,
                    (artifact_entry, pending_entry),
                    ambiguous_message="artifact cleanup is ambiguous",
                )
                raise
            try:
                os.fsync(directory_fd)
            except OSError as exc:
                raise ClientStateError("artifact commit durability is ambiguous", code="artifact_commit_ambiguous") from exc
            try:
                _bound_location(location, directory_fd)
            except ClientStateError:
                _cleanup_created(
                    directory_fd,
                    (metadata_entry, artifact_entry, pending_entry),
                    ambiguous_message="stale artifact cleanup is ambiguous",
                )
                raise
            _unlink_owned(directory_fd, pending_entry)
            try:
                os.fsync(directory_fd)
            except OSError as exc:
                raise ClientStateError("artifact commit durability is ambiguous", code="artifact_commit_ambiguous") from exc
            try:
                _bound_location(location, directory_fd)
            except ClientStateError:
                _cleanup_created(
                    directory_fd,
                    (metadata_entry, artifact_entry),
                    ambiguous_message="stale artifact cleanup is ambiguous",
                )
                raise
            return {"artifact": name, "metadata": metadata_name, "record": metadata}
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        os.close(directory_fd)
    raise ClientStateError("artifact collision limit exceeded for one millisecond", code="artifact_collision")


def verify_artifact(location: StateLocation, artifact_name: str, *, schema_path: Path) -> dict:
    parsed = parse_artifact_name(artifact_name)
    official_schema = _load_schema_file(_official_schema_path())
    metadata_schema = _load_schema_file(schema_path)
    metadata_schemas = (
        (official_schema,) if metadata_schema == official_schema else (official_schema, metadata_schema)
    )
    refresh_state_location(location, allow_created_roots=True)
    try:
        directory_fd = _open_location_directory(location, create=False)
    except OSError as exc:
        raise ClientStateError("client state root is unsafe or unavailable", code="unsafe_state_path") from exc
    try:
        current = _bound_location(location, directory_fd)
        try:
            content, artifact_details = _read_regular_with_identity(
                directory_fd, artifact_name, maximum=_MAX_ARTIFACT_BYTES
            )
            metadata_name = f"{artifact_name}.meta.json"
            metadata_bytes, metadata_details = _read_regular_with_identity(
                directory_fd, metadata_name, maximum=_MAX_METADATA_BYTES
            )
            artifact_entry = OwnedEntry(
                artifact_name, artifact_details.st_dev, artifact_details.st_ino,
                artifact_details.st_ctime_ns, hashlib.sha256(content).hexdigest(),
            )
            metadata_entry = OwnedEntry(
                metadata_name,
                metadata_details.st_dev,
                metadata_details.st_ino,
                metadata_details.st_ctime_ns,
                hashlib.sha256(metadata_bytes).hexdigest(),
            )
            metadata = json.loads(metadata_bytes.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ClientStateError("artifact or metadata is unreadable", code="invalid_artifact") from exc
        current = _bound_location(location, directory_fd)
    finally:
        os.close(directory_fd)
    if not isinstance(metadata, dict):
        raise ClientStateError("artifact metadata must be an object", code="invalid_metadata")
    for active_schema in metadata_schemas:
        if _schema_issues(metadata, active_schema):
            raise ClientStateError("artifact metadata failed schema validation", code="invalid_metadata")
    consumers = metadata.get("consumers")
    if (
        not isinstance(consumers, list)
        or any(not isinstance(item, str) for item in consumers)
        or consumers != sorted(set(consumers))
    ):
        raise ClientStateError("artifact consumers are not canonical", code="invalid_metadata")
    failures: list[str] = []
    if metadata.get("artifact") != artifact_name:
        failures.append("artifact path mismatch")
    if metadata.get("created_at") != parsed.created_at:
        failures.append("artifact timestamp mismatch")
    if metadata.get("format") != parsed.extension:
        failures.append("artifact format mismatch")
    digest = hashlib.sha256(content).hexdigest()
    if not _SHA256.fullmatch(str(metadata.get("content", {}).get("sha256", ""))) or metadata["content"]["sha256"] != digest:
        failures.append("content hash mismatch")
    if metadata.get("content", {}).get("size") != len(content):
        failures.append("content size mismatch")
    client = metadata.get("client", {})
    expected_client = {
        "key": current.client,
        "scope": current.scope,
        "registry_schema_version": current.registry_schema_version,
        "variant_digest": current.variant_digest,
    }
    if client != expected_client:
        failures.append("client registry snapshot mismatch")
    if current.git:
        repository = metadata.get("repository", {})
        if repository.get("root") != "." or repository.get("head") != current.git.head or repository.get("ref") != current.git.ref:
            failures.append("repository/ref snapshot is stale")
    elif "repository" in metadata:
        failures.append("global artifact contains a repository snapshot")
    refresh_state_location(location, allow_created_roots=True)
    try:
        final_fd = _open_location_directory(location, create=False)
    except OSError as exc:
        raise ClientStateError("client state root is unsafe or unavailable", code="unsafe_state_path") from exc
    try:
        current = _bound_location(location, final_fd)
        _assert_owned(final_fd, artifact_entry, maximum=_MAX_ARTIFACT_BYTES)
        _assert_owned(final_fd, metadata_entry)
        _bound_location(location, final_fd)
    finally:
        os.close(final_fd)
    return {"artifact": artifact_name, "failures": sorted(failures), "ok": not failures, "sha256": digest}
