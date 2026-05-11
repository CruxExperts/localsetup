from __future__ import annotations

import subprocess
from pathlib import Path


def tracked_files(repo_root: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return []
    return sorted(
        line
        for line in completed.stdout.splitlines()
        if line and (repo_root / line).exists()
    )


def classify_path(path: str) -> str:
    if (
        path.startswith(".agents/")
        or path.startswith(".localsetup-maint/")
        or path.startswith("docs/")
        or path.startswith("_localsetup/docs/local-context/")
        or path.startswith("scripts/")
        or path.startswith("state/")
    ):
        return "private-maintainer"
    if path.startswith("_localsetup/docs/_generated/"):
        return "generate"
    if path.startswith("_localsetup/skills/ls-"):
        return "keep"
    if path.startswith("_localsetup/skills/localsetup-"):
        return "legacy-migration"
    if path.startswith("_localsetup/workflows/ls-workflow-"):
        return "keep"
    if path == "install.ps1":
        return "refactor"
    if path.startswith("_localsetup/v3/") or path in {
        "_localsetup/config/pack.yaml",
        "_localsetup/config/platforms.yaml",
        "_localsetup/tools/localsetup_v3.py",
    }:
        return "refactor"
    if path.startswith("_localsetup/") or path in {"README.md", "AGENTS.md", "LICENSE", "SECURITY.md"}:
        return "keep"
    return "keep"


def implementation_file_map(repo_root: Path) -> list[dict]:
    rows: list[dict] = []
    for path in tracked_files(repo_root):
        classification = classify_path(path)
        if classification == "private-maintainer":
            continue
        rows.append({"path": path, "classification": classification})
    return rows
