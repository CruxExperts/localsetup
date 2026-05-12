from __future__ import annotations

import subprocess
from pathlib import Path


def source_commit(repo_root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return "unknown"
    return completed.stdout.strip()


def source_tag(repo_root: Path) -> str | None:
    completed = subprocess.run(
        ["git", "describe", "--tags", "--exact-match", "HEAD"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    tag = completed.stdout.strip()
    return tag or None
