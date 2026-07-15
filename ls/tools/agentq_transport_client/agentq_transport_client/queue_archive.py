#!/usr/bin/env python3
# Purpose: Prune queue archive/ by age and total size (agent_queue.example.yaml).
# Created: 2026-03-10
# Last updated: 2026-03-10

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any


def _dir_age_days(path: Path) -> float:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return 0.0
    return (time.time() - mtime) / 86400.0


def _dir_size_bytes(path: Path) -> int:
    total = 0
    try:
        for root, _dirs, files in os.walk(path):
            for f in files:
                fp = Path(root) / f
                try:
                    total += fp.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def prune_archive(
    archive_root: Path,
    *,
    older_than_days: float | None = None,
    max_total_gb: float | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    archive_root: typically queue_root/archive. Deletes subdirs oldest first
    until under max_total_gb; also removes dirs older than older_than_days.
    """
    archive_root = Path(archive_root)
    if not archive_root.is_dir():
        return {"status": "ok", "deleted": [], "bytes_freed": 0, "note": "no archive dir"}

    # Collect immediate subdirs with mtime
    dirs: list[tuple[float, Path]] = []
    for p in archive_root.iterdir():
        if p.is_dir():
            try:
                dirs.append((p.stat().st_mtime, p))
            except OSError:
                continue
    dirs.sort(key=lambda x: x[0])

    deleted: list[str] = []
    bytes_freed = 0

    # Age prune first
    if older_than_days is not None and older_than_days > 0:
        for _mt, p in list(dirs):
            if _dir_age_days(p) >= older_than_days:
                sz = _dir_size_bytes(p)
                if dry_run:
                    deleted.append(str(p))
                    bytes_freed += sz
                else:
                    try:
                        shutil.rmtree(p, ignore_errors=True)
                        deleted.append(str(p))
                        bytes_freed += sz
                    except OSError:
                        pass
                dirs = [d for d in dirs if d[1] != p]

    # Size prune: total remaining
    if max_total_gb is not None and max_total_gb > 0:
        max_bytes = int(max_total_gb * 1024**3)
        total = sum(_dir_size_bytes(d[1]) for d in dirs)
        for _mt, p in dirs:
            if total <= max_bytes:
                break
            sz = _dir_size_bytes(p)
            if dry_run:
                deleted.append(str(p))
                bytes_freed += sz
                total -= sz
            else:
                try:
                    shutil.rmtree(p, ignore_errors=True)
                    deleted.append(str(p))
                    bytes_freed += sz
                    total -= sz
                except OSError:
                    pass

    return {
        "status": "ok",
        "deleted": deleted,
        "bytes_freed": bytes_freed,
        "dry_run": dry_run,
    }
