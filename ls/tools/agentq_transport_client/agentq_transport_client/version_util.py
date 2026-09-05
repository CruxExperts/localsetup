#!/usr/bin/env python3
# Purpose: Read LocalSetup framework VERSION from project root for PRD stamping.
# Created: 2026-03-09
# Last updated: 2026-03-09

"""Resolve repo root VERSION file. Used by PRD generators and Agent Q client."""

from __future__ import annotations

import subprocess
from pathlib import Path


def get_engine_dir() -> Path:
    """Engine dir when this module is under ls/tools/agentq_transport_client/..."""
    return Path(__file__).resolve().parents[3]


def get_project_root() -> Path:
    """Project root (parent of ls)."""
    engine = get_engine_dir()
    if engine.name == "ls":
        return engine.parent
    return engine


def read_framework_version(default: str = "0.0.0") -> str:
    """Return VERSION file contents (stripped) or default if missing."""
    version_file = get_project_root() / "VERSION"
    if not version_file.is_file():
        return default
    return version_file.read_text(encoding="utf-8", errors="replace").strip() or default


def read_framework_hash() -> str | None:
    """Return short git sha if repo is a git checkout, else None."""
    root = get_project_root()
    git_dir = root / ".git"
    if not git_dir.exists():
        return None
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if out.returncode != 0 or not out.stdout.strip():
            return None
        return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
