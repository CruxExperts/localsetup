"""Read-only GitHub release identity and final documentation checks."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from ..git_subprocess import run_git


def gh_json(root: Path, *args: str) -> dict:
    result = subprocess.run(["gh", *args], cwd=root, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise ValueError("GitHub release lookup failed; no mutation is authorized by an uncertain lookup")
    return json.loads(result.stdout)


def git(root: Path, *args: str) -> str:
    result = run_git(root, list(args), capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise ValueError("Git identity lookup failed")
    return result.stdout.strip()


def published_baseline(root: Path, head: str) -> dict:
    release = gh_json(root, "api", "repos/{owner}/{repo}/releases/latest")
    tag = release.get("tag_name", "")
    if release.get("draft") or release.get("prerelease") or not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise ValueError("A published stable baseline is required")
    sha = git(root, "rev-parse", f"refs/tags/{tag}^{{commit}}")
    # Compare the remote tag too; annotated tags have a peeled ref.
    refs = git(root, "ls-remote", "origin", f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}")
    remote = {line.split()[1]: line.split()[0] for line in refs.splitlines()}
    if remote.get(f"refs/tags/{tag}^{{}}", remote.get(f"refs/tags/{tag}")) != sha:
        raise ValueError("Published baseline tag differs locally and remotely")
    git(root, "merge-base", "--is-ancestor", sha, head)
    if git(root, "show", f"{sha}:VERSION") != tag[1:]:
        raise ValueError("Published baseline VERSION differs from its tag")
    return {"tag": tag, "commit": sha, "version": tag[1:]}


def check_draft(root: Path, tag: str, record: dict, expected_commit: str) -> dict:
    from .render import notes

    if tag != "v" + record["version"]:
        raise ValueError("Draft tag differs from release documentation")
    release = gh_json(root, "release", "view", tag, "--json",
                      "tagName,targetCommitish,isDraft,body,assets")
    resolved = git(root, "rev-parse", f"refs/tags/{tag}^{{commit}}")
    if resolved != expected_commit:
        raise ValueError("Draft tag does not identify the checked commit")
    remote_refs = git(root, "ls-remote", "origin", f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}")
    remote = {line.split()[1]: line.split()[0] for line in remote_refs.splitlines()}
    if release["tagName"] != tag or remote.get(f"refs/tags/{tag}^{{}}", remote.get(f"refs/tags/{tag}")) != resolved:
        raise ValueError("Remote draft tag differs from the checked commit")
    if not release["isDraft"]:
        raise ValueError("Final-publication check requires an unpublished draft")
    if release["body"].strip() != notes(record).strip():
        raise ValueError("Draft release notes differ from checked documentation")
    archive = f"localsetup-{tag}.tar.gz"
    required = {archive, archive + ".sha256", archive + ".cdx.json"}
    if not required.issubset({asset["name"] for asset in release["assets"]}):
        raise ValueError("Draft is missing documented archive verification assets")
    return {"ok": True, "tag": tag, "commit": resolved,
            "artifact_scope": "documentation assets only; complete artifact verification remains required"}


def guard_repair(root: Path, baseline: dict, head: str) -> None:
    """A published repair cannot describe executable work awaiting a new release."""
    changed = git(root, "diff", "--name-only", baseline["commit"], head, "--").splitlines()
    allowed = {"README.md", "ls/README.md", "assets/README.md"}
    if any(path not in allowed and not (path.startswith("ls/docs/") and path.endswith((".md", ".json")))
           for path in changed):
        raise ValueError("Repair refused: main contains unreleased non-documentation changes")
