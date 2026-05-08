"""Audit logging helpers for OmniRoute admin tooling."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .util import ensure_parent_dir, now_iso, redact_payload


class AuditLogger:
    """Writes append-only JSONL events for operation traceability."""

    def __init__(self, run_id: str, base_dir: str = "state/audit") -> None:
        self.run_id = run_id
        self.base_dir = Path(base_dir)
        self.file_path = self.base_dir / f"{run_id}.jsonl"
        ensure_parent_dir(self.file_path)

    def log(self, event: str, payload: dict[str, Any]) -> None:
        entry = {
            "timestamp": now_iso(),
            "run_id": self.run_id,
            "event": event,
            "payload": redact_payload(payload),
        }
        encoded = json.dumps(entry, sort_keys=True)
        entry["digest_sha256"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        with self.file_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
