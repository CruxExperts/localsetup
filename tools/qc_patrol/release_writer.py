from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .deterministic_checks import check_release_exclusions


def release_readiness(repo: Path, out: Path) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    artifact = out / "localsetup-qc-release.tar.gz"
    build = subprocess.run(["uv", "run", "--locked", "python", "_localsetup/tools/localsetup.py", "--source-root", ".", "package", "--out", str(artifact)], cwd=repo, text=True, capture_output=True)
    findings = check_release_exclusions(repo, artifact if artifact.exists() else None)
    verify = None
    if build.returncode == 0:
        verify = subprocess.run(["uv", "run", "--locked", "python", "_localsetup/tools/localsetup.py", "--source-root", ".", "verify-release", str(artifact)], cwd=repo, text=True, capture_output=True)
    return {
        "schema_version": "qc.release-readiness.v1",
        "artifact": str(artifact),
        "package_returncode": build.returncode,
        "verify_returncode": verify.returncode if verify else None,
        "findings": findings,
    }
