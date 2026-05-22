from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .schemas import LEDGER_SCHEMA, LEDGER_V2_SCHEMA, validate_payload


def write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def build_ledger(command: str, findings: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    payload = {
        "schema_version": "qc.ledger.v1",
        "created_at_unix": int(time.time()),
        "command": command,
        "ok": not any(finding.get("severity") in {"high", "critical"} for finding in findings),
        "findings": findings,
    }
    payload.update(extra)
    errors = validate_payload(payload, LEDGER_SCHEMA)
    if errors:
        raise ValueError("invalid QC ledger: " + "; ".join(errors))
    return payload


def build_ledger_v2(
    command: str,
    deterministic_findings: list[dict[str, Any]],
    *,
    head_sha: str,
    ai_mode: str,
    ai_findings: list[dict[str, Any]] | None = None,
    issue_results: list[dict[str, Any]] | None = None,
    artifacts: dict[str, str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    ai_findings = ai_findings or []
    blocking = [
        *deterministic_findings,
        *(finding for finding in ai_findings if finding.get("should_create_issue")),
    ]
    payload = {
        "schema_version": "qc.ledger.v2",
        "created_at_unix": int(time.time()),
        "command": command,
        "ok": not any(finding.get("severity") in {"high", "critical"} for finding in blocking),
        "head_sha": head_sha,
        "deterministic_findings": deterministic_findings,
        "ai_findings": ai_findings,
        "rule_suggestions": extra.pop("rule_suggestions", {"schema_version": "qc.rule-suggestions.v1", "suggestions": []}),
        "issue_results": issue_results or [],
        "artifacts": artifacts or {},
        "ai_mode": ai_mode,
    }
    payload.update(extra)
    errors = validate_payload(payload, LEDGER_V2_SCHEMA)
    if errors:
        raise ValueError("invalid QC ledger v2: " + "; ".join(errors))
    return payload
