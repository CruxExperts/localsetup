from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def _git_files(repo: Path) -> list[str]:
    result = subprocess.run(["git", "ls-files"], cwd=repo, check=True, text=True, capture_output=True)
    return sorted(line for line in result.stdout.splitlines() if line)


def build_inventory(repo: Path) -> dict[str, Any]:
    files = _git_files(repo)
    return {
        "schema_version": "qc.inventory.v1",
        "tracked_file_count": len(files),
        "workflows": [path for path in files if path.startswith(".github/workflows/")],
        "package_surfaces": [path for path in files if path in {"pyproject.toml", "uv.lock", "VERSION"}],
        "public_private_config": "_localsetup/config/pack.yaml" in files,
        "validation_commands": [
            "uv run --locked pytest -n auto _localsetup/tests -q",
            "uv run --locked ./_localsetup/tests/automated_test.sh",
        ],
        "files": files[:5000],
    }
