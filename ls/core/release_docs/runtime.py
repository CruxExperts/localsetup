"""Provision a protected completion runtime from a verified published wheel.

No version solving: dependencies are downloaded against the wheel's hashed
exports, then installed through the existing offline runtime owner.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile

from .github import gh_json, published_baseline, git


def provision(root: Path, runtime_root: Path, assets_dir: Path, python: str) -> dict:
    from ..agent.runtime_install import install

    if assets_dir.exists() or runtime_root.exists():
        raise ValueError("Runtime provisioning needs fresh task-specific paths; inspect existing state instead of replaying")
    if runtime_root.resolve().is_relative_to(root.resolve()) or root.resolve().is_relative_to(runtime_root.resolve()):
        raise ValueError("Protected runtime must be outside the repository")
    baseline = published_baseline(root, git(root, "rev-parse", "HEAD"))
    print(json.dumps({"stage": "verified-baseline"}), flush=True)
    release = gh_json(root, "api", "repos/{owner}/{repo}/releases/tags/" + baseline["tag"])
    wheels = [item for item in release["assets"]
              if item["name"] == f"localsetup-{baseline['version']}-py3-none-any.whl"]
    if len(wheels) != 1 or not re.fullmatch(r"sha256:[0-9a-f]{64}", wheels[0].get("digest") or ""):
        raise ValueError("Published wheel needs a trusted GitHub asset digest")
    assets_dir.mkdir(parents=True, mode=0o700)
    wheel = assets_dir / wheels[0]["name"]
    subprocess.run(["gh", "release", "download", baseline["tag"], "--pattern", wheel.name,
                    "--dir", str(assets_dir)], cwd=root, check=True, timeout=120)
    digest = wheels[0]["digest"].split(":", 1)[1]
    if hashlib.sha256(wheel.read_bytes()).hexdigest() != digest:
        raise ValueError("Downloaded runtime wheel differs from the published digest")
    print(json.dumps({"stage": "verified-wheel"}), flush=True)
    with zipfile.ZipFile(wheel) as archive:
        for name in ("sdk-build.lock", "sdk-runtime.lock"):
            (assets_dir / name).write_bytes(archive.read("ls/config/" + name))
    wheelhouse = assets_dir / "wheelhouse"
    wheelhouse.mkdir()
    environment = {key: value for key, value in os.environ.items()
                   if key in {"PATH", "LANG", "LC_ALL", "SYSTEMROOT", "TMPDIR"}}
    environment.update(PIP_CONFIG_FILE=os.devnull, PIP_NO_INPUT="1",
                       PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_CACHE_DIR=str(assets_dir / "pip-cache"))
    for name in ("sdk-build.lock", "sdk-runtime.lock"):
        print(json.dumps({"stage": "download", "lock": name}), flush=True)
        result = subprocess.run([python, "-m", "pip", "download", "--disable-pip-version-check",
                        "--require-hashes", "--no-deps", "--no-build-isolation",
                        "--dest", str(wheelhouse), "-r", str(assets_dir / name)],
                       cwd=assets_dir, check=False, timeout=300, stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE, text=True, env=environment)
        if result.returncode:
            # Never disclose raw pip output: URLs may contain index credentials.
            reason = "download command failed"
            for marker, label in (("No module named pip", "pip unavailable"),
                                  ("No matching distribution", "locked distribution unavailable"),
                                  ("DO NOT MATCH THE HASHES", "dependency hash mismatch"),
                                  ("metadata-generation-failed", "source metadata generation failed")):
                if marker in result.stderr:
                    reason = label
                    break
            raise ValueError(f"{name}: {reason} (exit {result.returncode})")
    print(json.dumps({"stage": "install-protected-runtime"}), flush=True)
    result = install(runtime_root, wheel, digest, wheelhouse, root, timeout=300)
    return {"ok": True, "baseline": baseline, "wheel_sha256": digest,
            "runtime_status": result.get("status", "installed")}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--assets-dir", type=Path, required=True)
    parser.add_argument("--python", required=True, help="Provisioned runner Python with pip")
    args = parser.parse_args()
    try:
        print(json.dumps(provision(args.repo_root.resolve(), args.runtime_root.resolve(),
                                   args.assets_dir.resolve(), args.python)))
        return 0
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError, KeyError) as exc:
        # Only our fixed download classifications are safe outward diagnostics.
        detail = str(exc) if re.fullmatch(r"sdk-(?:build|runtime)\.lock: [a-z ]+ \(exit [0-9]+\)", str(exc)) else type(exc).__name__
        print(json.dumps({"ok": False, "reason": "Protected runtime provisioning failed", "detail": detail}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
