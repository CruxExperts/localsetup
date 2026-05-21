from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .deterministic_checks import finding


def docs_alignment_findings(repo: Path) -> list[dict[str, Any]]:
    result = subprocess.run(
        ["uv", "run", "--locked", "python", "_localsetup/tools/docs_alignment.py", "--repo-root", ".", "check", "--ci"],
        cwd=repo,
        text=True,
        capture_output=True,
    )
    if result.returncode == 0:
        return []
    return [
        finding(
            "docs",
            "medium",
            "Docs alignment check failed",
            "The docs alignment CI check reported drift or contract findings.",
            "_localsetup/tools/docs_alignment.py",
            region="docs-align check --ci",
            check_type="docs_alignment",
        )
    ]
