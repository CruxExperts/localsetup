#!/usr/bin/env python3
# Purpose: Append-only ingest ledger JSONL for idempotency.
# Created: 2026-03-09
# Last updated: 2026-03-09

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def ledger_path(queue_root: Path) -> Path:
    return Path(queue_root) / "inbox" / ".ingest_log.jsonl"


def blob_id(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def append_event(
    queue_root: Path,
    event_type: str,
    payload: dict[str, Any],
    *,
    transport_id: str | None = None,
) -> None:
    """Append one JSON line; create parent dirs."""
    path = ledger_path(queue_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
        "transport_id": transport_id,
        **payload,
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")


def ship_ledger_path(queue_root: Path) -> Path:
    """Outbound ship events; keeps ingest ledger separate."""
    p = Path(queue_root) / "out" / ".ship_log.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def append_ship_event(
    queue_root: Path,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """ship_push_ok | ship_push_fail | ship_mail_ok | ship_mail_fail"""
    path = ship_ledger_path(queue_root)
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
        **payload,
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")


def already_ingested(queue_root: Path, transport_id: str) -> bool:
    p = ledger_path(queue_root)
    if not p.is_file():
        return False
    tid = (transport_id or "").strip()
    if not tid:
        return False
    with open(p, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if o.get("transport_id") == tid and o.get("event") in (
                "ingest_promote_ok",
                "ingest_forced",
            ):
                return True
    return False


def iter_ingest_events(
    queue_root: Path, event_type: str | None = None
):
    """Yield parsed JSON objects from ingest ledger."""
    p = ledger_path(queue_root)
    if not p.is_file():
        return
    with open(p, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event_type and o.get("event") != event_type:
                continue
            yield o


def pending_processed_moves(queue_root: Path) -> list[dict[str, Any]]:
    """Ledger records with event pending_processed_move (mail-move-retry)."""
    return list(iter_ingest_events(queue_root, "pending_processed_move"))
