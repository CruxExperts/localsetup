from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .schemas import LEDGER_SCHEMA, validate_payload


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
