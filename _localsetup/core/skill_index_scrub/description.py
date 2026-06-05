from __future__ import annotations

import re
from typing import Optional

import frontmatter

from .config import sanitize
from .constants import DEFAULT_TIMEOUT, MAX_DESC_LEN, MIN_DESC_LEN_DEFAULT, STUB_PATTERNS
from .diagnostics import debug
from .http import fetch_text, raw_skill_candidates


def extract_description_from_content(text: str) -> Optional[str]:
    """
    Parse frontmatter with python-frontmatter; use description field if present
    and long enough, otherwise fall back to the first substantive paragraph.
    """
    try:
        post = frontmatter.loads(text)
        desc = (post.metadata.get("description") or "").strip()
        if len(desc) > 15:
            return desc[:MAX_DESC_LEN]
        for para in re.split(r"\n\s*\n", post.content):
            clean = re.sub(r"[#*`>\[\]|]", "", para).strip()
            clean = sanitize(clean)
            if len(clean) > 25:
                return clean[:MAX_DESC_LEN]
    except Exception:
        pass
    return None


def fetch_upstream_description(skill_url: str, timeout: int = DEFAULT_TIMEOUT) -> tuple[Optional[str], Optional[str]]:
    """
    Try to fetch a description from the skill's upstream repo.
    Returns (description, source_url_used) or (None, None).
    """
    candidates = raw_skill_candidates(skill_url)
    for raw_url in candidates:
        debug(f"Trying upstream: {raw_url}")
        status, body = fetch_text(raw_url, timeout=timeout)
        if status == 200 and len(body) > 50:
            desc = extract_description_from_content(body)
            if desc:
                return desc, raw_url
    return None, None


def is_stub_description(desc: str, min_len: int = MIN_DESC_LEN_DEFAULT) -> tuple[bool, str]:
    """
    Returns (is_stub, reason).
    A stub is empty, too short, matches a known placeholder pattern, or is a raw markdown artifact.
    """
    if not desc or not desc.strip():
        return True, "empty"
    desc = desc.strip()
    if len(desc) < min_len:
        return True, f"too_short ({len(desc)} chars)"
    for pattern in STUB_PATTERNS:
        if pattern.search(desc):
            return True, f"placeholder_pattern ({pattern.pattern!r})"
    if desc.startswith("```") or desc.startswith("|.") or desc.startswith(">-"):
        return True, "markdown_artifact"
    return False, ""
