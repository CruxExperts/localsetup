"""Explicit integration of an accepted documentation candidate, never force-push."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

from .github import git


def integrate(root: Path, evidence: Path, *, push: bool = False) -> dict:
    from .application import apply_candidate
    from ..versioning import publish_preflight

    saved = json.loads(evidence.read_text())
    source = saved["plan"]["source_commit"]
    if git(root, "rev-parse", "HEAD") != source:
        raise ValueError("Candidate source changed; re-prepare")
    if push and git(root, "ls-remote", "origin", "refs/heads/main").split()[0] != source:
        raise ValueError("Remote main advanced; re-prepare without force-pushing")
    result = apply_candidate(root, saved["plan"], saved["candidate"])
    if not result["changed_paths"]:
        return {"ok": True, "head": source, "changed": False}
    subprocess.run(["git", "add", "--", *result["changed_paths"]], cwd=root, check=True)
    # Authored release preparation belongs to the already planned release.
    subprocess.run(["git", "-c", "user.name=github-actions[bot]", "-c",
                    "user.email=41898282+github-actions[bot]@users.noreply.github.com",
                    "commit", "-m", "docs: prepare release documentation", "-m", "Release-Type: none"],
                   cwd=root, check=True)
    baseline = saved["plan"].get("published_baseline", {}).get("commit") or saved["plan"].get("baseline_tag", source)
    prepared = publish_preflight(root, base=baseline, head="HEAD", fix=True)
    if not prepared["ok"]:
        raise ValueError("Canonical publication preflight failed after documentation preparation")
    subprocess.run(["uv", "run", "--frozen", "python", "ls/tools/localsetup.py", "--source-root", ".",
                    "release-docs", "check"], cwd=root, check=True)
    subprocess.run(["uv", "run", "--frozen", "python", "ls/tools/docs_alignment.py", "--repo-root", ".",
                    "check", "--ci"], cwd=root, check=True)
    subprocess.run(["uv", "run", "--frozen", "python", "ls/tools/validate_branding.py", "--repo-root", ".",
                    "--strict"], cwd=root, check=True, stdout=subprocess.DEVNULL)
    if git(root, "status", "--porcelain"):
        raise ValueError("Candidate validation changed tracked files; no push attempted")
    head = git(root, "rev-parse", "HEAD")
    if push:
        if git(root, "ls-remote", "origin", "refs/heads/main").split()[0] != source:
            raise ValueError("Remote main advanced; candidate retained locally, no push attempted")
        subprocess.run(["git", "push", "origin", "HEAD:refs/heads/main"], cwd=root, check=True, timeout=120)
    return {"ok": True, "head": head, "changed": True}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--push", action="store_true")
    args = parser.parse_args()
    try:
        result = integrate(Path.cwd(), args.candidate, push=args.push)
        print(json.dumps(result))
        # GitHub output is a trusted exact commit, never model text.
        import os
        output = os.environ.get("GITHUB_OUTPUT")
        if output:
            with open(output, "a", encoding="utf-8") as stream:
                stream.write("head=" + result["head"] + "\n")
        return 0
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        print(json.dumps({"ok": False, "reason": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
