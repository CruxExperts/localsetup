from __future__ import annotations

import re
import tarfile
from pathlib import Path
from typing import Any

import yaml


PINNED_ACTION_RE = re.compile(r"^[^@]+@[0-9a-f]{40}(?:\\s*#.*)?$")
QC_WORKFLOWS = {
    ".github/workflows/qc-ci.yml",
    ".github/workflows/qc-pr-review.yml",
    ".github/workflows/qc-patrol.yml",
    ".github/workflows/qc-docs-drift.yml",
    ".github/workflows/qc-release.yml",
    ".github/workflows/qc-autofix.yml",
}


def finding(category: str, severity: str, title: str, body: str, path: str, *, region: str = "", check_type: str = "deterministic") -> dict[str, Any]:
    return {
        "category": category,
        "severity": severity,
        "title": title,
        "body": body,
        "affected_paths": [path] if path else [],
        "region": region,
        "check_type": check_type,
    }


def _load_workflow(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def scan_workflow_permissions(repo: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for workflow in sorted((repo / ".github/workflows").glob("*.yml")):
        rel = workflow.relative_to(repo).as_posix()
        data = _load_workflow(workflow)
        if "permissions" not in data:
            findings.append(finding("workflow_security", "medium", f"{rel} has no explicit permissions", "Workflows should define default token permissions explicitly.", rel, region="permissions"))
        if "pull_request_target" in (data.get(True) or data.get("on") or {}):
            text = workflow.read_text(encoding="utf-8")
            if "actions/checkout" in text and "github.event.pull_request.head.repo.fork" not in text and "dependabot" not in text:
                findings.append(finding("workflow_security", "high", f"{rel} uses pull_request_target without an obvious guard", "Privileged PR workflows need explicit untrusted-fork protections.", rel, region="pull_request_target"))
        for job_name, job in (data.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            permissions = job.get("permissions", data.get("permissions", {}))
            if isinstance(permissions, dict):
                for scope, value in permissions.items():
                    if value == "write" and scope not in {"contents", "issues", "pull-requests", "id-token", "attestations"}:
                        findings.append(finding("workflow_security", "medium", f"{rel} grants unexpected {scope}: write", "Unexpected write scopes should be reviewed.", rel, region=str(job_name)))
            for step in job.get("steps", []) or []:
                if not isinstance(step, dict) or "uses" not in step:
                    continue
                uses = str(step["uses"])
                if uses.startswith("./"):
                    continue
                if not PINNED_ACTION_RE.match(uses):
                    findings.append(finding("workflow_security", "low", f"{rel} uses unpinned action {uses}", "External actions should be pinned to full commit SHAs.", rel, region=str(job_name)))
    return findings


def check_release_exclusions(repo: Path, artifact: Path | None = None) -> list[dict[str, Any]]:
    pack = repo / "ls/config/pack.yaml"
    data = yaml.safe_load(pack.read_text(encoding="utf-8")) or {}
    private = set((data.get("public_private") or {}).get("private_paths") or [])
    findings: list[dict[str, Any]] = []
    missing = sorted(QC_WORKFLOWS - private)
    for path in missing:
        findings.append(finding("release", "high", f"{path} is not excluded from release artifact", "QC workflows rely on root tools/qc_patrol, which is not part of the Localsetup framework package.", "ls/config/pack.yaml", region=path))
    if artifact and artifact.exists():
        with tarfile.open(artifact, "r:*") as tar:
            names = set(tar.getnames())
        for path in sorted(QC_WORKFLOWS & names):
            findings.append(finding("release", "high", f"{path} was included in release artifact", "QC workflows must not ship without their root tooling.", path, region="artifact"))
    return findings


def run_deterministic(repo: Path, profile: str, artifact: Path | None = None) -> list[dict[str, Any]]:
    findings = scan_workflow_permissions(repo)
    if profile in {"ci", "release"}:
        findings.extend(check_release_exclusions(repo, artifact))
    return findings
