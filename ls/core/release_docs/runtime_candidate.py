"""Bind the protected completion wheel to the exact checked-out candidate."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

from .github import git
from ..sdk_payload.artifacts import inspect_artifact
from ..sdk_payload.sbom import SBOM_PATH


def build_candidate(root: Path, assets: Path, baseline_wheel: Path,
                    python: str, environment: dict[str, str]) -> dict:
    source = git(root, "rev-parse", "HEAD")
    if git(root, "status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("Candidate runtime requires a clean source checkout")
    output = assets / "candidate-wheel"
    output.mkdir(mode=0o700)
    subprocess.run(["uv", "--no-config", "build", "--wheel", "--offline",
                    "--no-build-isolation", "--python", python,
                    "--config-settings=--global-option=build",
                    "--config-settings=--global-option=--build-base=" + str(assets / "build"),
                    "--out-dir", str(output)], cwd=root, env=environment,
                   check=True, timeout=180, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    wheels = list(output.glob("*.whl"))
    if len(wheels) != 1 or wheels[0].is_symlink():
        raise ValueError("Candidate build must produce one regular wheel")
    wheel = wheels[0]
    inspect_artifact(wheel)
    with zipfile.ZipFile(baseline_wheel) as baseline, zipfile.ZipFile(wheel) as candidate:
        if candidate.read("ls/_sdk_payload/manifest.json") != baseline.read("ls/_sdk_payload/manifest.json"):
            raise ValueError("Candidate SDK payload differs from verified baseline")
        for name in ("sdk-build.lock", "sdk-runtime.lock"):
            member = "ls/config/" + name
            if candidate.read(member) != baseline.read(member):
                raise ValueError("Candidate SDK dependencies differ from verified baseline")
        members = candidate.namelist()
        if len(members) != len(set(members)):
            raise ValueError("Candidate wheel contains duplicate members")
        tracked = set(git(root, "ls-files", "ls").splitlines())
        verified = []
        for member in members:
            if not member.startswith("ls/") or member.endswith("/"):
                continue
            if member.startswith("ls/_sdk_payload/") or member == SBOM_PATH:
                continue  # Separately verified by the SDK artifact inspector.
            if member not in tracked:
                raise ValueError("Candidate wheel contains untracked package content")
            original = subprocess.run(["git", "show", source + ":" + member],
                                      cwd=root, check=True, capture_output=True).stdout
            if candidate.read(member) != original:
                raise ValueError("Candidate wheel content differs from source commit")
            verified.append(member)
        if "ls/core/agent/provider_client.py" not in verified:
            raise ValueError("Candidate wheel lacks completion transport")
    if git(root, "rev-parse", "HEAD") != source or git(root, "status", "--porcelain"):
        raise ValueError("Candidate source changed during runtime build")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    receipt = {"source_commit": source, "wheel_sha256": digest,
               "verified_source_members": len(verified), "dependencies": "published-baseline"}
    (assets / "candidate-runtime.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return {**receipt, "wheel": wheel}
