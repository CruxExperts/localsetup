"""Reject obvious private or credential material in outward documentation edits."""
from __future__ import annotations

import re


_FORBIDDEN = (
    re.compile(r"\[(?:REDACTED|REDACTED_URL|REDACTED_TOKEN)[^\]]*\]"),
    re.compile(r"\b(?:ghp_|github_pat_|sk-[A-Za-z0-9_-]{16}|xox[baprs]-)[A-Za-z0-9_-]+"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"https?://[^\s/@]+:[^\s/@]+@"),
    re.compile(r"(?:/home/|/Users/|/mnt/data/)[A-Za-z0-9_.-]+/"),
)


def check_public_text(text: str) -> None:
    if any(pattern.search(text) for pattern in _FORBIDDEN):
        raise ValueError("Documentation contains private material or a redaction placeholder; nothing published")
