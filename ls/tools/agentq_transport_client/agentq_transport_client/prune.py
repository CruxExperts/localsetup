#!/usr/bin/env python3
# Purpose: Prune processed subdirs older than N days (spec M6).
# Created: 2026-03-09
# Last updated: 2026-03-09

from __future__ import annotations

import shutil
import time
from pathlib import Path


def prune_processed(
    processed_root: Path,
    *,
    older_than_days: float,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Remove entries under processed_root with mtime older than cutoff.
    Returns {removed: [...], skipped: count, dry_run: bool}.
    """
    processed_root = Path(processed_root)
    if not processed_root.is_dir():
        return {"removed": [], "skipped": 0, "error": "not_a_dir"}
    cutoff = time.time() - (older_than_days * 86400)
    removed: list[str] = []
    skipped = 0
    for child in processed_root.iterdir():
        if not child.is_dir():
            skipped += 1
            continue
        try:
            mtime = child.stat().st_mtime
        except OSError:
            skipped += 1
            continue
        if mtime < cutoff:
            if dry_run:
                removed.append(str(child))
            else:
                shutil.rmtree(child, ignore_errors=True)
                removed.append(str(child))
    return {"removed": removed, "skipped": skipped, "dry_run": dry_run}
