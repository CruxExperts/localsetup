from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import Baseline, BaselineEntry, Finding


SCHEMA_VERSION = "1.0"


class BaselineError(ValueError):
    """Raised when the architecture baseline cannot be loaded."""


def _require_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise BaselineError(f"baseline field {key!r} must be a string")
    return value


def _require_int(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    if not isinstance(value, int):
        raise BaselineError(f"baseline field {key!r} must be an integer")
    return value


def load_baseline(path: Path) -> Baseline:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise BaselineError(f"cannot read baseline {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise BaselineError(f"baseline {path} is not valid JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise BaselineError("baseline root must be an object")
    schema_version = _require_string(raw, "schema_version")
    generated_at = _require_string(raw, "generated_at")
    scope = _require_string(raw, "scope")
    entries_raw = raw.get("entries")
    if not isinstance(entries_raw, list):
        raise BaselineError("baseline field 'entries' must be a list")

    entries: list[BaselineEntry] = []
    for index, entry_raw in enumerate(entries_raw):
        if not isinstance(entry_raw, dict):
            raise BaselineError(f"baseline entry {index} must be an object")
        metric = _require_string(entry_raw, "metric")
        if metric != "lines":
            raise BaselineError(f"baseline entry {index} has unsupported metric {metric!r}")
        entries.append(
            BaselineEntry(
                id=_require_string(entry_raw, "id"),
                path=_require_string(entry_raw, "path"),
                metric="lines",
                current_value=_require_int(entry_raw, "current_value"),
                threshold=_require_int(entry_raw, "threshold"),
                reason=_require_string(entry_raw, "reason"),
                owner=_require_string(entry_raw, "owner"),
                expires=entry_raw.get("expires") if isinstance(entry_raw.get("expires"), str) else None,
                notes=entry_raw.get("notes") if isinstance(entry_raw.get("notes"), str) else None,
            )
        )

    return Baseline(
        schema_version=schema_version,
        generated_at=generated_at,
        scope=scope,
        entries=tuple(entries),
    )


def baseline_metadata_findings(baseline: Baseline) -> list[Finding]:
    findings: list[Finding] = []
    for entry in baseline.entries:
        if not entry.reason.strip() or not entry.owner.strip():
            findings.append(
                Finding(
                    code="PYA003_BASELINE_MISSING_REASON",
                    severity="error",
                    path=entry.path,
                    message="Baseline entry must include non-empty reason and owner.",
                    metric=entry.metric,
                    current_value=entry.current_value,
                    threshold=entry.threshold,
                )
            )
    return findings
