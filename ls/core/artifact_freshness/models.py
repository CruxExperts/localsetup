from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal


ReviewState = Literal["current", "review_date_stale"]
TargetState = Literal["versioned", "unversioned", "not_applicable"]
RiskClass = Literal["low", "medium", "high", "critical"]


class ArtifactFreshnessError(ValueError):
    """Base error for invalid artifact freshness metadata or evaluation input."""

    def __init__(self, message: str, *, issues: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.issues = issues


class ArtifactFreshnessSchemaError(ArtifactFreshnessError):
    """Raised when metadata does not satisfy the JSON schema."""


class ArtifactFreshnessSemanticError(ArtifactFreshnessError):
    """Raised when metadata passes structure checks but violates domain rules."""


@dataclass(frozen=True, slots=True)
class ArtifactFreshnessRecord:
    """Validated, portable freshness metadata with parsed calendar dates."""

    schema_version: int
    artifact_id: str
    artifact_type: str
    owner: str
    source: str
    target_state: TargetState
    verification_date: date
    verification_method: str
    authoritative_sources: tuple[str, ...]
    review_interval_days: int
    risk_class: RiskClass
    content_sha256: str | None = None
    target_kind: str | None = None
    target_name: str | None = None
    target_version: str | None = None
    target_reason: str | None = None
    superseded_by: str | None = None

    @property
    def review_date(self) -> date:
        """Return the inclusive last date on which review is current."""

        return self.verification_date + timedelta(days=self.review_interval_days)


@dataclass(frozen=True, slots=True)
class ReviewResult:
    """Deterministic review state for one record and one caller-supplied UTC date."""

    state: ReviewState
    review_date: date
    evaluated_date: date

    @property
    def is_current(self) -> bool:
        return self.state == "current"
