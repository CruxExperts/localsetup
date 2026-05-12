from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def write_trace(path: str | None, *, event: str, status: str, attributes: dict[str, Any] | None = None, started_at: float | None = None) -> None:
    if not path:
        return
    now = time.time()
    payload = {
        "timestamp_unix": now,
        "event": event,
        "status": status,
        "duration_ms": int((now - started_at) * 1000) if started_at is not None else None,
        "attributes": attributes or {},
    }
    trace_path = Path(path).expanduser().resolve()
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    with trace_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
