from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .github_api import GitHubAPI


BLOCK_RE = re.compile(r"```qc.issue-handoff.v1\n(.*?)\n```", re.DOTALL)


def normalize_title(title: str) -> str:
    return " ".join(title.lower().split())


def fingerprint_for(finding: dict[str, Any]) -> str:
    material = "|".join(
        [
            str(finding.get("category", "")),
            str(finding.get("check_type", "")),
            normalize_title(str(finding.get("title", ""))),
            str((finding.get("affected_paths") or [""])[0]),
            str(finding.get("region", "")),
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def extract_handoff(body: str) -> dict[str, Any] | None:
    match = BLOCK_RE.search(body or "")
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def issue_body(finding: dict[str, Any]) -> str:
    handoff = {"schema_version": "qc.issue-handoff.v1", "fingerprint": fingerprint_for(finding), "finding": finding}
    return f"{finding['body']}\n\n```qc.issue-handoff.v1\n{json.dumps(handoff, indent=2, sort_keys=True)}\n```\n"


def labels_for(finding: dict[str, Any], base_labels: list[str]) -> list[str]:
    return sorted(set(base_labels + [f"qc/category/{finding['category']}", f"qc/severity/{finding['severity']}"]))


def find_duplicate(issues: list[dict[str, Any]], finding: dict[str, Any]) -> dict[str, Any] | None:
    target = fingerprint_for(finding)
    for issue in issues:
        handoff = extract_handoff(str(issue.get("body", "")))
        if handoff and handoff.get("fingerprint") == target:
            return issue
    return None


def write_issues(findings: list[dict[str, Any]], labels: list[str], *, dry_run: bool = False, api: GitHubAPI | None = None) -> list[dict[str, Any]]:
    api = api or GitHubAPI.from_env()
    existing = api.list_open_issues("qc-patrol") if api.enabled() and not dry_run else []
    results: list[dict[str, Any]] = []
    for finding in findings:
        title = f"[QC][{finding['category']}] {finding['title']}"
        duplicate = find_duplicate(existing, finding)
        if duplicate:
            action = "comment"
            if api.enabled() and not dry_run:
                api.comment_issue(int(duplicate["number"]), "Fresh QC observation for this fingerprint.")
        else:
            action = "create"
            if api.enabled() and not dry_run:
                api.create_issue(title, issue_body(finding), labels_for(finding, labels))
        results.append({"action": action, "title": title, "fingerprint": fingerprint_for(finding)})
    return results
