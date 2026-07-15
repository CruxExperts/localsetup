#!/usr/bin/env python3
# Purpose: Repo-local path resolution for Python tooling (mirrors data_paths.sh).
# Created: 2026-02-20
# Last updated: 2026-02-20

"""
Path resolution for framework tools. Use get_engine_dir() and get_project_root()
so scripts work from repo root or from engine dir. Respects LOCALSETUP_FRAMEWORK_DIR
and LOCALSETUP_PROJECT_ROOT when set.
"""

import os
from pathlib import Path


def get_engine_dir() -> Path:
    """Engine dir = directory containing lib/, tools/, skills/."""
    env_dir = os.environ.get("LOCALSETUP_FRAMEWORK_DIR", "").strip()
    if env_dir and Path(env_dir).is_dir():
        return Path(env_dir).resolve()
    # Assume we are in ls/lib/path_resolution.py or ls/tools/script.py
    this_file = Path(__file__).resolve()
    if this_file.name == "path_resolution.py" and "lib" in this_file.parts:
        return this_file.parent.parent
    if "tools" in this_file.parts:
        return this_file.parent.parent
    return this_file.parent


def get_project_root() -> Path:
    """Client repo root (parent of ls when deployed)."""
    env_root = os.environ.get("LOCALSETUP_PROJECT_ROOT", "").strip()
    if env_root and Path(env_root).is_dir():
        return Path(env_root).resolve()
    engine = get_engine_dir()
    parent = engine.parent
    if parent.name == "ls":
        return parent.parent
    return parent


def get_user_data_dir() -> Path:
    """User data dir: prefer repo-local."""
    env_data = os.environ.get("LOCALSETUP_PROJECT_DATA", "").strip()
    if env_data and Path(env_data).is_dir():
        return Path(env_data).resolve()
    env_root = os.environ.get("LOCALSETUP_PROJECT_ROOT", "").strip()
    if env_root:
        root = Path(env_root).resolve()
        return root / ".localsetup-project"
    root = get_project_root()
    return root / ".localsetup-project"


if __name__ == "__main__":
    print("engine:", get_engine_dir())
    print("root:", get_project_root())
    print("user_data:", get_user_data_dir())
