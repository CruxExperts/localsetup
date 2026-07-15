#!/usr/bin/env python3
# Purpose: Minimal queue layout ops: promote in/ to pending/ when ack_required.
# Created: 2026-03-10
# Last updated: 2026-03-10

"""Filesystem-only; reads manifest.json or first .prd.md frontmatter not parsed; optional JSON manifest only."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


def _manifest_in_dir(d: Path) -> dict[str, Any] | None:
    mj = d / "manifest.json"
    if mj.is_file():
        try:
            m = json.loads(mj.read_text(encoding="utf-8"))
            return m if isinstance(m, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def list_in_ready(queue_root: Path) -> list[dict[str, Any]]:
    """List in/<id>/ with optional manifest summary."""
    inbox = Path(queue_root) / "in"
    if not inbox.is_dir():
        return []
    out = []
    for child in sorted(inbox.iterdir()):
        if not child.is_dir():
            continue
        m = _manifest_in_dir(child)
        out.append(
            {
                "id": child.name,
                "path": str(child),
                "ack_required": bool(m.get("ack_required")) if m else False,
                "conversation_id": (m or {}).get("conversation_id"),
            }
        )
    return out


def move_to_pending(queue_root: Path, transport_id: str) -> dict[str, Any]:
    """Move in/<id> to pending/<id> if exists."""
    queue_root = Path(queue_root)
    src = queue_root / "in" / transport_id
    if not src.is_dir():
        return {"status": "error", "code": "NOT_FOUND", "path": str(src)}
    dest = queue_root / "pending" / transport_id
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return {"status": "error", "code": "TARGET_EXISTS", "path": str(dest)}
    shutil.move(str(src), str(dest))
    return {"status": "ok", "from": str(src), "to": str(dest)}


def move_ack_required_to_pending(queue_root: Path) -> list[dict[str, Any]]:
    """Scan in/*; if manifest has ack_required true, move to pending/."""
    results = []
    for row in list_in_ready(queue_root):
        if not row.get("ack_required"):
            continue
        tid = row["id"]
        r = move_to_pending(queue_root, tid)
        r["id"] = tid
        results.append(r)
    return results
