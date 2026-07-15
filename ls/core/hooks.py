from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from .docs import generate_alias_outputs
from .package import build_public_artifact


def run_maintainer_gate(repo_root: Path, artifact_path: Path, runner: str | None = None) -> dict:
    docs = generate_alias_outputs(repo_root)
    package = build_public_artifact(repo_root, artifact_path)
    result = {
        "docs": docs,
        "package": package,
        "agent_runner": None,
        "ok": not package["leaks"],
    }

    runner_cmd = runner or os.environ.get("LOCALSETUP_AGENT_RUNNER")
    if runner_cmd:
        completed = subprocess.run(
            runner_cmd.split(),
            cwd=repo_root,
            env={**os.environ, "LOCALSETUP_AGENT_NETWORK": "0"},
            text=True,
            capture_output=True,
            timeout=int(os.environ.get("LOCALSETUP_AGENT_TIMEOUT", "30")),
            check=False,
        )
        runner_payload = {
            "returncode": completed.returncode,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
        }
        try:
            runner_payload["json"] = json.loads(completed.stdout)
        except json.JSONDecodeError:
            runner_payload["json"] = None
        result["agent_runner"] = runner_payload
        result["ok"] = bool(result["ok"] and completed.returncode == 0)

    return result
