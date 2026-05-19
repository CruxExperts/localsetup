from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any


GIT_ENV_TO_SCRUB = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_NAMESPACE",
)


def git_subprocess_env() -> dict[str, str]:
    """Return an environment for repo-local Git commands."""
    env = os.environ.copy()
    for name in GIT_ENV_TO_SCRUB:
        env.pop(name, None)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return env


def run_git(repo_root: Path, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
    """Run Git from an explicit repo root without inherited scratch Git state."""
    kwargs.setdefault("cwd", repo_root)
    kwargs["env"] = git_subprocess_env()
    return subprocess.run(["git", *args], **kwargs)
