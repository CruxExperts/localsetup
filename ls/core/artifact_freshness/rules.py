from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from re import fullmatch
from typing import Any
from urllib.parse import urlparse

from .models import (
    ArtifactFreshnessRecord,
    ArtifactFreshnessSemanticError,
    ReviewResult,
    ReviewState,
)

_TARGET_STATES = {"versioned", "unversioned", "not_applicable"}
_RISK_CLASSES = {"low", "medium", "high", "critical"}
_DATE_PATTERN = r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
_SHA256_PATTERN = r"[0-9a-fA-F]{64}"


def parse_utc_date(value: Any, *, field: str) -> date:
    """Parse one strict ISO UTC calendar date without accepting timestamps."""

    if type(value) is date:
        return value
    if type(value) is not str or fullmatch(_DATE_PATTERN, value) is None:
        raise ArtifactFreshnessSemanticError(
            f"{field} must be a UTC calendar date in YYYY-MM-DD form",
            issues=(f"{field} must be a UTC calendar date in YYYY-MM-DD form",),
        )
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ArtifactFreshnessSemanticError(
            f"{field} is not a valid UTC calendar date",
            issues=(f"{field} is not a valid UTC calendar date",),
        ) from exc
    if parsed.isoformat() != value:
        raise ArtifactFreshnessSemanticError(
            f"{field} must use canonical YYYY-MM-DD form",
            issues=(f"{field} must use canonical YYYY-MM-DD form",),
        )
    return parsed


def _is_https_url(value: Any) -> bool:
    if type(value) is not str or not value or any(character.isspace() for character in value):
        return False
    try:
        parsed = urlparse(value)
        hostname = parsed.hostname
        parsed.port
    except ValueError:
        return False
    return parsed.scheme == "https" and bool(hostname)


def semantic_issues(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Return deterministic cross-field validation issues for schema-shaped data."""

    issues: list[str] = []
    if not isinstance(payload, Mapping):
        return ("metadata must be an object",)

    target_state = payload.get("target_state")
    if target_state not in _TARGET_STATES:
        issues.append("target_state must be versioned, unversioned, or not_applicable")
    elif target_state == "versioned":
        for field in ("target_kind", "target_name", "target_version"):
            value = payload.get(field)
            if not isinstance(value, str) or not value:
                issues.append(f"versioned target requires non-empty {field}")
        sources = payload.get("authoritative_sources")
        if not isinstance(sources, (list, tuple)) or not sources:
            issues.append("versioned target requires at least one authoritative source")
    else:
        if not isinstance(payload.get("target_reason"), str) or not payload["target_reason"]:
            issues.append(f"{target_state} target requires a non-empty target_reason")
        if payload.get("target_version") is not None:
            issues.append(f"{target_state} target cannot claim target_version")

    verification_date = payload.get("verification_date")
    try:
        parse_utc_date(verification_date, field="verification_date")
    except ArtifactFreshnessSemanticError as exc:
        issues.extend(exc.issues)

    sources = payload.get("authoritative_sources")
    if not isinstance(sources, (list, tuple)) or not sources:
        issues.append("authoritative_sources must contain at least one HTTPS URL")
    else:
        for index, source in enumerate(sources):
            if not _is_https_url(source):
                issues.append(f"authoritative_sources[{index}] must be an HTTPS URL")

    interval = payload.get("review_interval_days")
    if isinstance(interval, bool) or not isinstance(interval, int) or interval < 1:
        issues.append("review_interval_days must be a positive integer")

    risk_class = payload.get("risk_class")
    if risk_class not in _RISK_CLASSES:
        issues.append("risk_class must be low, medium, high, or critical")

    content_sha256 = payload.get("content_sha256")
    if content_sha256 is not None and (
        not isinstance(content_sha256, str) or fullmatch(_SHA256_PATTERN, content_sha256) is None
    ):
        issues.append("content_sha256 must be exactly 64 hexadecimal characters")

    return tuple(issues)


def evaluate_review_state(record: ArtifactFreshnessRecord, evaluated_on: date | str) -> ReviewResult:
    """Evaluate a validated record on a caller-provided UTC calendar date."""

    if not isinstance(record, ArtifactFreshnessRecord):
        issue = "record must be an ArtifactFreshnessRecord"
        raise ArtifactFreshnessSemanticError(issue, issues=(issue,))
    evaluated_date = parse_utc_date(evaluated_on, field="evaluated_on")
    review_date = record.review_date
    state: ReviewState = "current" if evaluated_date <= review_date else "review_date_stale"
    return ReviewResult(state=state, review_date=review_date, evaluated_date=evaluated_date)
