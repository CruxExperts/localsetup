"""Markdown link scan helpers for run_framework_audit."""

from __future__ import annotations

import re
from pathlib import Path

PLAIN_SEE_DOCS = re.compile(r"\b[Ss]ee\s+docs/[^\s\]\)\"']+")
PLAIN_SEE_LOCALSETUP = re.compile(r"\b[Ss]ee\s+ls/[^\s\]\)\"']+")


def phase_link_checks(root: Path) -> list[tuple[str, int, str]]:
    """Return list of (file, line_no, snippet) for plain doc references."""
    findings: list[tuple[str, int, str]] = []
    for md in root.rglob("*.md"):
        try:
            rel = md.relative_to(root)
            if "_generated" in rel.parts or "node_modules" in rel.parts:
                continue
            text = md.read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue
        for i, line in enumerate(text.split("\n"), 1):
            if "](docs/" in line or "](ls/" in line:
                continue
            if PLAIN_SEE_DOCS.search(line) or PLAIN_SEE_LOCALSETUP.search(line):
                findings.append((str(rel), i, line.strip()[:80]))
    return findings
