from __future__ import annotations

import re
from typing import Optional

import requests

from .constants import DEFAULT_TIMEOUT, TOOL_NAME, TOOL_VERSION, UPSTREAM_FILENAMES
from .diagnostics import debug


def tree_to_raw(url: str) -> str:
    """Convert a github.com tree URL to raw.githubusercontent.com."""
    raw = url.replace("https://github.com/", "https://raw.githubusercontent.com/")
    return re.sub(r"/tree/(main|master)/", r"/\1/", raw)


def raw_skill_candidates(tree_url: str) -> list[str]:
    """
    Build a list of raw URLs to try for description fetching.
    If the tree_url already ends in .md, use it directly then strip to directory.
    Otherwise treat as directory and try each upstream filename candidate.
    """
    raw_base = tree_to_raw(tree_url)
    candidates = []

    if raw_base.endswith(".md"):
        candidates.append(raw_base)
        base_dir = raw_base.rsplit("/", 1)[0]
        for filename in UPSTREAM_FILENAMES:
            alt = f"{base_dir}/{filename}"
            if alt not in candidates:
                candidates.append(alt)
    else:
        base_dir = raw_base.rstrip("/")
        for filename in UPSTREAM_FILENAMES:
            candidates.append(f"{base_dir}/{filename}")

    return candidates


def make_session() -> requests.Session:
    sess = requests.Session()
    sess.headers["User-Agent"] = f"localsetup-{TOOL_NAME}/{TOOL_VERSION}"
    return sess


SESSION: Optional[requests.Session] = None


def session() -> requests.Session:
    global SESSION
    if SESSION is None:
        SESSION = make_session()
    return SESSION


def check_url_liveness(url: str, timeout: int = DEFAULT_TIMEOUT) -> tuple[bool, int]:
    """
    Returns (is_live, status_code).
    Tries HEAD first; falls back to GET if HEAD returns 405.
    """
    sess = session()
    try:
        resp = sess.head(url, timeout=timeout, allow_redirects=True)
        status = resp.status_code
        if status == 405:
            resp = sess.get(url, timeout=timeout, allow_redirects=True)
            status = resp.status_code
    except requests.RequestException as exc:
        debug(f"HEAD {url} => network error: {exc}")
        return False, 0
    live = 200 <= status < 400
    return live, status


def fetch_text(url: str, timeout: int = DEFAULT_TIMEOUT) -> tuple[int, str]:
    """GET url; returns (status_code, body). On network error returns (0, '')."""
    sess = session()
    try:
        resp = sess.get(url, timeout=timeout, allow_redirects=True)
        return resp.status_code, resp.text
    except requests.RequestException as exc:
        debug(f"GET {url} => network error: {exc}")
        return 0, ""
