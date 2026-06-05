from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


Severity = Literal["warning", "error"]
Metric = Literal["lines"]


@dataclass(frozen=True)
class BaselineEntry:
    id: str
    path: str
    metric: Metric
    current_value: int
    threshold: int
    reason: str
    owner: str
    expires: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class Baseline:
    schema_version: str
    generated_at: str
    scope: str
    entries: tuple[BaselineEntry, ...]


@dataclass(frozen=True)
class FileMetric:
    path: str
    line_count: int
    absolute_path: Path


@dataclass(frozen=True)
class Finding:
    code: str
    severity: Severity
    path: str
    message: str
    metric: str | None = None
    current_value: int | None = None
    threshold: int | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity,
            "path": self.path,
            "message": self.message,
        }
        if self.metric is not None:
            payload["metric"] = self.metric
        if self.current_value is not None:
            payload["current_value"] = self.current_value
        if self.threshold is not None:
            payload["threshold"] = self.threshold
        return payload


@dataclass(frozen=True)
class CheckSummary:
    repo_root: str
    include_scope: str
    fail_on: str
    scanned_files: int
    findings: tuple[Finding, ...] = field(default_factory=tuple)

    @property
    def errors(self) -> tuple[Finding, ...]:
        return tuple(finding for finding in self.findings if finding.severity == "error")

    @property
    def warnings(self) -> tuple[Finding, ...]:
        return tuple(finding for finding in self.findings if finding.severity == "warning")

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": not self.errors,
            "repo_root": self.repo_root,
            "include_scope": self.include_scope,
            "fail_on": self.fail_on,
            "scanned_files": self.scanned_files,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "findings": [finding.as_dict() for finding in self.findings],
        }
