from __future__ import annotations

from pathlib import Path

from .git_subprocess import run_git


def source_commit(repo_root: Path) -> str:
    completed = run_git(
        repo_root,
        ["rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return "unknown"
    return completed.stdout.strip()


def source_tag(repo_root: Path) -> str | None:
    completed = run_git(
        repo_root,
        ["describe", "--tags", "--exact-match", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    tag = completed.stdout.strip()
    return tag or None
