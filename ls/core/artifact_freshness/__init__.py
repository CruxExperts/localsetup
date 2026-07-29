from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from ..schema import validate_json_schema
from .models import (
    ArtifactFreshnessError,
    ArtifactFreshnessRecord,
    ArtifactFreshnessSchemaError,
    ArtifactFreshnessSemanticError,
    ReviewResult,
    ReviewState,
    RiskClass,
    TargetState,
)
from .rules import evaluate_review_state, parse_utc_date, semantic_issues

_SCHEMA_RELATIVE_PATH = Path("ls") / "config" / "artifact-freshness.schema.json"


def _schema_path(repo_root: Path | str | None, schema_path: Path | str | None) -> Path:
    if schema_path is not None:
        return Path(schema_path)
    if repo_root is None:
        issue = "repo_root or schema_path is required to locate the freshness schema"
        raise ArtifactFreshnessSchemaError(issue, issues=(issue,))
    return Path(repo_root) / _SCHEMA_RELATIVE_PATH


def validate_artifact_freshness(
    payload: Mapping[str, Any],
    repo_root: Path | str | None = None,
    *,
    schema_path: Path | str | None = None,
) -> ArtifactFreshnessRecord:
    """Validate metadata against the repository-relative schema and domain rules."""

    if not isinstance(payload, Mapping):
        issue = "metadata must be an object"
        raise ArtifactFreshnessSchemaError(issue, issues=(issue,))
    data = payload if isinstance(payload, dict) else dict(payload)
    resolved_schema_path = _schema_path(repo_root, schema_path)
    if not resolved_schema_path.is_file():
        issue = f"freshness schema does not exist: {resolved_schema_path}"
        raise ArtifactFreshnessSchemaError(issue, issues=(issue,))
    try:
        schema_issues = validate_json_schema(
            data,
            resolved_schema_path,
            label="artifact freshness metadata",
            required=True,
        )
    except (OSError, ValueError) as exc:
        issue = f"could not load freshness schema {resolved_schema_path}: {exc}"
        raise ArtifactFreshnessSchemaError(issue, issues=(issue,)) from exc
    if schema_issues:
        raise ArtifactFreshnessSchemaError("; ".join(schema_issues), issues=tuple(schema_issues))

    domain_issues = semantic_issues(data)
    if domain_issues:
        raise ArtifactFreshnessSemanticError("; ".join(domain_issues), issues=domain_issues)

    target_state = cast(TargetState, data["target_state"])
    risk_class = cast(RiskClass, data["risk_class"])
    return ArtifactFreshnessRecord(
        schema_version=cast(int, data["schema_version"]),
        artifact_id=cast(str, data["artifact_id"]),
        artifact_type=cast(str, data["artifact_type"]),
        owner=cast(str, data["owner"]),
        source=cast(str, data["source"]),
        target_state=target_state,
        verification_date=parse_utc_date(data["verification_date"], field="verification_date"),
        verification_method=cast(str, data["verification_method"]),
        authoritative_sources=tuple(cast(list[str], data["authoritative_sources"])),
        review_interval_days=cast(int, data["review_interval_days"]),
        risk_class=risk_class,
        content_sha256=cast(str | None, data.get("content_sha256")),
        target_kind=cast(str | None, data.get("target_kind")),
        target_name=cast(str | None, data.get("target_name")),
        target_version=cast(str | None, data.get("target_version")),
        target_reason=cast(str | None, data.get("target_reason")),
        superseded_by=cast(str | None, data.get("superseded_by")),
    )


def load_artifact_freshness(
    payload: Mapping[str, Any],
    repo_root: Path | str | None = None,
    *,
    schema_path: Path | str | None = None,
) -> ArtifactFreshnessRecord:
    """Load and validate one caller-provided metadata mapping."""

    return validate_artifact_freshness(payload, repo_root, schema_path=schema_path)


__all__ = [
    "ArtifactFreshnessError",
    "ArtifactFreshnessRecord",
    "ArtifactFreshnessSchemaError",
    "ArtifactFreshnessSemanticError",
    "ReviewResult",
    "ReviewState",
    "RiskClass",
    "TargetState",
    "evaluate_review_state",
    "load_artifact_freshness",
    "parse_utc_date",
    "semantic_issues",
    "validate_artifact_freshness",
]
