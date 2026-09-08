"""Release-document record validation and committed-file loading."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ls.core.versioning_models import SemVer


_SHA = re.compile(r"[0-9a-f]{40}\Z")
_PATH = re.compile(r"(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9._/@+,-]+(?:/[A-Za-z0-9._/@+,-]+)*\Z")
_FIELDS = {
    "schema_version",
    "version",
    "source_commit",
    "baseline_tag",
    "summary",
    "highlights",
    "compatibility",
    "update",
    "verification",
}


def _string(value: object, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"Release record {name} must be a non-empty string")
    return value


def _string_list(value: object, name: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"Release record {name} must be a non-empty list of strings")
    if len(value) > 64 or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"Release record {name} must be a bounded list of non-empty strings")
    return value


def _evidence(value: object) -> list[str]:
    values = _string_list(value, "highlight evidence")
    for item in values:
        if not (_SHA.fullmatch(item) or _PATH.fullmatch(item)):
            raise ValueError("Release record evidence must be a full commit SHA or a safe repo-relative path")
    return values


def validate_record(record: object) -> dict[str, Any]:
    """Validate and return a release-document record without touching the filesystem."""
    if not isinstance(record, dict) or set(record) != _FIELDS:
        raise ValueError("Release record has invalid fields")
    if type(record["schema_version"]) is not int or record["schema_version"] != 1:
        raise ValueError("Release record schema_version must be 1")
    version = _string(record["version"], "version")
    if str(SemVer.parse(version)) != version:
        raise ValueError("Release record version must be a canonical semantic version")
    source_commit = _string(record["source_commit"], "source_commit")
    if not _SHA.fullmatch(source_commit):
        raise ValueError("Release record source_commit must be a full commit SHA")
    baseline_tag = _string(record["baseline_tag"], "baseline_tag")
    if not baseline_tag.startswith("v") or str(SemVer.parse(baseline_tag[1:])) != baseline_tag[1:]:
        raise ValueError("Release record baseline_tag must be a canonical version tag")
    highlights = record["highlights"]
    if not isinstance(highlights, list) or not highlights or len(highlights) > 32:
        raise ValueError("Release record highlights must be a non-empty bounded list")
    normalized_highlights: list[dict[str, Any]] = []
    for item in highlights:
        if not isinstance(item, dict) or set(item) != {"text", "evidence"}:
            raise ValueError("Release record highlight must contain text and evidence")
        normalized_highlights.append({"text": _string(item["text"], "highlight text"), "evidence": _evidence(item["evidence"])})
    return {
        "schema_version": 1,
        "version": version,
        "source_commit": source_commit,
        "baseline_tag": baseline_tag,
        "summary": _string(record["summary"], "summary"),
        "highlights": normalized_highlights,
        "compatibility": _string_list(record["compatibility"], "compatibility"),
        "update": _string_list(record["update"], "update"),
        "verification": _string_list(record["verification"], "verification"),
    }


def load_record(repo_root: Path, version: str) -> dict[str, Any]:
    """Load a versioned record from the source tree and validate its identity."""
    if str(SemVer.parse(version)) != version:
        raise ValueError("Release record version must be canonical")
    path = Path(repo_root) / "ls" / "docs" / "releases" / f"{version}.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Release record is missing: {path.relative_to(repo_root)}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Release record is invalid JSON: {path.relative_to(repo_root)}") from exc
    record = validate_record(value)
    if record["version"] != version:
        raise ValueError("Release record filename and version differ")
    return record
