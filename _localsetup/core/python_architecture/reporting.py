from __future__ import annotations

import json

from .models import CheckSummary


def render_json(summary: CheckSummary) -> str:
    return json.dumps(summary.as_dict(), indent=2, sort_keys=True) + "\n"


def render_markdown(summary: CheckSummary) -> str:
    lines = [
        "# Python Architecture Check",
        "",
        f"- ok: `{str(not summary.errors).lower()}`",
        f"- scanned_files: `{summary.scanned_files}`",
        f"- errors: `{len(summary.errors)}`",
        f"- warnings: `{len(summary.warnings)}`",
        "",
    ]
    if not summary.findings:
        lines.append("No findings.")
        return "\n".join(lines) + "\n"

    lines.extend(["| Severity | Code | Path | Message |", "|---|---|---|---|"])
    for finding in summary.findings:
        message = finding.message.replace("|", "\\|")
        lines.append(f"| {finding.severity} | `{finding.code}` | `{finding.path}` | {message} |")
    return "\n".join(lines) + "\n"
