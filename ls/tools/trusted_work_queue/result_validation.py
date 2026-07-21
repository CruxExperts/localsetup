"""Validate opaque returned patch deposits against a published candidate fanout."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FANOUT_FILENAME = "fanout.json"
RESULT_FILENAME = "result.json"
PATCH_FILENAME = "patch.diff"
RESULT_FORMAT_VERSION = 1
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ResultValidationError(Exception):
    """A returned patch deposit does not bind to the expected candidate snapshot."""


@dataclass(frozen=True)
class PatchResult:
    """A verified opaque patch and its exact fanout provenance."""

    result_dir: Path
    manifest_path: Path
    patch_path: Path
    job_id: str
    candidate_id: str
    archive_sha256: str
    git_head: str | None
    patch_sha256: str
    patch_bytes: int


def validate_patch_result(
    fanout_path: str | os.PathLike[str],
    result_dir: str | os.PathLike[str],
) -> PatchResult:
    """Validate a byte-preserving patch deposit without parsing or applying it.

    The result directory must contain exactly the expected regular members:
    `result.json` and opaque `patch.diff`. Validation anchors its directory and
    reads every control member through no-follow file descriptors. It binds them
    to a published `fanout.json` job and candidate identifier. It does not
    execute, parse, or apply patch text; return transport, acceptance, retention,
    and any durable patch copy remain owned by later controller phases.

    ``PatchResult.patch_path`` identifies the validated deposit location, not an
    immutable artifact. A later consumer must copy or revalidate the patch before
    using that mutable pathname.
    """
    _, fanout_payload = _read_regular_json_path(
        fanout_path,
        field="fanout manifest",
    )
    fanout = _read_fanout(fanout_payload)
    directory, directory_descriptor = _open_directory(result_dir, field="result directory")
    try:
        _require_exact_result_members(directory_descriptor)
        result_descriptor = _open_regular_at(
            directory_descriptor,
            RESULT_FILENAME,
            field="result manifest",
        )
        try:
            result = _read_json_descriptor(result_descriptor, field="result manifest")
        finally:
            os.close(result_descriptor)
        _validate_result_schema(result)

        patch_descriptor = _open_regular_at(
            directory_descriptor,
            PATCH_FILENAME,
            field="returned patch",
        )
        try:
            patch_sha256, patch_bytes = _hash_descriptor(patch_descriptor)
        finally:
            os.close(patch_descriptor)
        _require_exact_result_members(directory_descriptor)
    finally:
        os.close(directory_descriptor)

    candidate_ids = {entry["candidate_id"] for entry in fanout["candidates"]}
    if result["job_id"] != fanout["job_id"]:
        raise ResultValidationError("returned patch job does not match fanout")
    if result["candidate_id"] not in candidate_ids:
        raise ResultValidationError("returned patch candidate is not in fanout")
    if result["archive_sha256"] != fanout["archive_sha256"]:
        raise ResultValidationError("returned patch snapshot digest does not match fanout")
    if result["git_head"] != fanout["git_head"]:
        raise ResultValidationError("returned patch Git provenance does not match fanout")
    if patch_sha256 != result["patch_sha256"] or patch_bytes != result["patch_bytes"]:
        raise ResultValidationError("returned patch bytes do not match result manifest")
    return PatchResult(
        result_dir=directory,
        manifest_path=directory / RESULT_FILENAME,
        patch_path=directory / PATCH_FILENAME,
        job_id=result["job_id"],
        candidate_id=result["candidate_id"],
        archive_sha256=result["archive_sha256"],
        git_head=result["git_head"],
        patch_sha256=patch_sha256,
        patch_bytes=patch_bytes,
    )


def _read_fanout(payload: dict[str, Any]) -> dict[str, Any]:
    expected_fields = {
        "format_version",
        "job_id",
        "archive_sha256",
        "archive_bytes",
        "git_head",
        "source_root_name",
        "prd_sha256",
        "prd_bytes",
        "replication_count",
        "claim_retained",
        "candidates",
    }
    if set(payload) != expected_fields:
        raise ResultValidationError("fanout manifest has an unsupported schema")
    if payload["format_version"] != 1:
        raise ResultValidationError("fanout manifest version is unsupported")
    _require_sha256(payload["job_id"], field="fanout job")
    _require_sha256(payload["archive_sha256"], field="fanout archive")
    if not _is_plain_int(payload["archive_bytes"]) or payload["archive_bytes"] < 0:
        raise ResultValidationError("fanout archive byte count is invalid")
    if payload["git_head"] is not None and not isinstance(payload["git_head"], str):
        raise ResultValidationError("fanout Git provenance is invalid")
    if not isinstance(payload["source_root_name"], str) or not payload["source_root_name"]:
        raise ResultValidationError("fanout source root is invalid")
    _require_sha256(payload["prd_sha256"], field="fanout PRD")
    if not _is_plain_int(payload["prd_bytes"]) or payload["prd_bytes"] < 0:
        raise ResultValidationError("fanout PRD byte count is invalid")
    if not _is_plain_int(payload["replication_count"]) or payload["replication_count"] < 1:
        raise ResultValidationError("fanout replication count is invalid")
    if payload["claim_retained"] is not True:
        raise ResultValidationError("fanout claim retention is invalid")
    candidates = payload["candidates"]
    if not isinstance(candidates, list) or len(candidates) != payload["replication_count"]:
        raise ResultValidationError("fanout candidates are invalid")
    candidate_ids: set[str] = set()
    for entry in candidates:
        if not isinstance(entry, dict) or set(entry) != {"candidate_id", "repository", "prd"}:
            raise ResultValidationError("fanout candidate schema is invalid")
        candidate_id = entry["candidate_id"]
        if not isinstance(candidate_id, str) or not re.fullmatch(r"candidate-[0-9]{3}", candidate_id):
            raise ResultValidationError("fanout candidate identifier is invalid")
        if candidate_id in candidate_ids:
            raise ResultValidationError("fanout candidate identifier is duplicated")
        candidate_ids.add(candidate_id)
        expected_repository = f"{candidate_id}/{payload['source_root_name']}"
        expected_prd = f"{candidate_id}/prd.bin"
        if entry["repository"] != expected_repository or entry["prd"] != expected_prd:
            raise ResultValidationError("fanout candidate paths are invalid")
    return payload


def _validate_result_schema(payload: dict[str, Any]) -> None:
    expected_fields = {
        "format_version",
        "job_id",
        "candidate_id",
        "archive_sha256",
        "git_head",
        "patch_sha256",
        "patch_bytes",
    }
    if set(payload) != expected_fields:
        raise ResultValidationError("result manifest has an unsupported schema")
    if payload["format_version"] != RESULT_FORMAT_VERSION:
        raise ResultValidationError("result manifest version is unsupported")
    _require_sha256(payload["job_id"], field="result job")
    if not isinstance(payload["candidate_id"], str) or not re.fullmatch(r"candidate-[0-9]{3}", payload["candidate_id"]):
        raise ResultValidationError("result candidate identifier is invalid")
    _require_sha256(payload["archive_sha256"], field="result archive")
    if payload["git_head"] is not None and not isinstance(payload["git_head"], str):
        raise ResultValidationError("result Git provenance is invalid")
    _require_sha256(payload["patch_sha256"], field="result patch")
    if not _is_plain_int(payload["patch_bytes"]) or payload["patch_bytes"] < 0:
        raise ResultValidationError("result patch byte count is invalid")


def _open_directory(
    value: str | os.PathLike[str],
    *,
    field: str,
) -> tuple[Path, int]:
    path = Path(value).expanduser()
    flags = _safe_open_flags() | os.O_DIRECTORY
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ResultValidationError(f"{field} cannot be opened safely") from exc
    try:
        mode = os.fstat(descriptor).st_mode
    except OSError as exc:
        os.close(descriptor)
        raise ResultValidationError(f"{field} cannot be inspected") from exc
    if not stat.S_ISDIR(mode):
        os.close(descriptor)
        raise ResultValidationError(f"{field} must be a non-symlink directory")
    return path, descriptor


def _read_regular_json_path(
    value: str | os.PathLike[str],
    *,
    field: str,
) -> tuple[Path, dict[str, Any]]:
    path = Path(value).expanduser()
    descriptor = _open_regular_path(path, field=field)
    try:
        return path, _read_json_descriptor(descriptor, field=field)
    finally:
        os.close(descriptor)


def _open_regular_path(value: Path, *, field: str) -> int:
    try:
        descriptor = os.open(value, _safe_open_flags())
    except OSError as exc:
        raise ResultValidationError(f"{field} cannot be opened safely") from exc
    return _require_regular_descriptor(descriptor, field=field)


def _open_regular_at(directory_descriptor: int, name: str, *, field: str) -> int:
    try:
        descriptor = os.open(name, _safe_open_flags(), dir_fd=directory_descriptor)
    except OSError as exc:
        raise ResultValidationError(f"{field} cannot be opened safely") from exc
    return _require_regular_descriptor(descriptor, field=field)


def _require_regular_descriptor(descriptor: int, *, field: str) -> int:
    try:
        mode = os.fstat(descriptor).st_mode
    except OSError as exc:
        os.close(descriptor)
        raise ResultValidationError(f"{field} cannot be inspected") from exc
    if not stat.S_ISREG(mode):
        os.close(descriptor)
        raise ResultValidationError(f"{field} must be a regular non-symlink file")
    return descriptor


def _require_exact_result_members(directory_descriptor: int) -> None:
    try:
        members = set(os.listdir(directory_descriptor))
    except OSError as exc:
        raise ResultValidationError("result directory cannot be listed safely") from exc
    if members != {RESULT_FILENAME, PATCH_FILENAME}:
        raise ResultValidationError("result directory must contain exactly result.json and patch.diff")


def _safe_open_flags() -> int:
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None:
        raise ResultValidationError("safe result validation requires O_NOFOLLOW")
    return os.O_RDONLY | no_follow | getattr(os, "O_CLOEXEC", 0)


def _read_json_descriptor(descriptor: int, *, field: str) -> dict[str, Any]:
    try:
        with os.fdopen(os.dup(descriptor), "rb") as handle:
            loaded = json.loads(handle.read().decode("ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ResultValidationError(f"{field} cannot be read") from exc
    if not isinstance(loaded, dict):
        raise ResultValidationError(f"{field} must be a JSON object")
    return loaded


def _hash_descriptor(descriptor: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    try:
        with os.fdopen(os.dup(descriptor), "rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
                total += len(chunk)
    except OSError as exc:
        raise ResultValidationError("returned patch cannot be read") from exc
    return digest.hexdigest(), total


def _require_sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ResultValidationError(f"{field} digest is invalid")
    return value


def _is_plain_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
