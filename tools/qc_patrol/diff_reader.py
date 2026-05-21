from __future__ import annotations

import subprocess
from pathlib import Path

from .redaction import redact_text


def fetch_ref(repo: Path, remote: str, ref: str) -> None:
    subprocess.run(["git", "fetch", "--no-tags", "--depth=1", remote, ref], cwd=repo, text=True, capture_output=True, check=True)


def read_diff(repo: Path, base: str, head: str) -> str:
    result = subprocess.run(["git", "diff", "--find-renames", "--unified=80", f"{base}...{head}"], cwd=repo, text=True, capture_output=True)
    if result.returncode != 0:
        result = subprocess.run(["git", "diff", "--find-renames", "--unified=80", f"{base}", f"{head}"], cwd=repo, text=True, capture_output=True, check=True)
    return redact_text(result.stdout)
