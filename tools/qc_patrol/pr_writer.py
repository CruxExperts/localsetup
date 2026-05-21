from __future__ import annotations

from pathlib import Path
from typing import Any


ALLOWLIST = {"generated-docs-refresh"}


def plan_autofix(issue: str, *, dry_run: bool, create_pr: bool, out: Path) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    allowed = issue in ALLOWLIST
    return {
        "schema_version": "qc.autofix.v1",
        "issue": issue,
        "allowed": allowed,
        "dry_run": dry_run,
        "create_pr": create_pr and allowed and not dry_run,
        "message": "Autofix v1 is limited to generated docs refresh. Non-allowlisted remediation is issue-only.",
    }
