"""
Purpose: Shared helpers for CLI-based skills (pipx/path handling and status artifacts).
Created: 2026-03-16
Last Updated: 2026-03-16
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def pipx_app_bin_dir() -> Path:
    """
    Return the expected directory where user-level pipx installs CLI entrypoints.
    """
    return Path.home() / ".local" / "bin"


def augment_path_for_pipx_apps() -> Tuple[str, str]:
    """
    Ensure the user-level pipx app directory is present in PATH for the current
    process and any child processes spawned from it.
    """
    bin_dir = str(pipx_app_bin_dir())
    old_path = os.environ.get("PATH", "")
    parts = old_path.split(":") if old_path else []
    if bin_dir not in parts:
        parts.append(bin_dir)
    new_path = ":".join(p.strip() for p in parts if p.strip())
    os.environ["PATH"] = new_path
    return old_path, new_path


@dataclass
class CommandStatus:
    command: List[str]
    returncode: int
    stdout: str
    stderr: str
    created_at: str


def write_status_artifact(
    base_path: Path,
    payload: Dict,
    suffix: str = ".status.json",
) -> Path:
    """
    Write a status JSON file next to a primary output or under a well-known
    directory. Returns the resulting path.
    """
    status_path = base_path.with_suffix(base_path.suffix + suffix)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    if "created_at" not in payload:
        payload["created_at"] = utc_now_iso()
    status_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return status_path
