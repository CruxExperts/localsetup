from __future__ import annotations

from .constants import DEFAULT_TIMEOUT, HARD_DEAD_URL_STATUSES, MIN_DESC_LEN_DEFAULT
from .description import fetch_upstream_description, is_stub_description
from .diagnostics import debug
from .http import check_url_liveness

NO_LICENSE_DESCRIPTION_SOURCE_REGISTRIES = {
    "https://github.com/anthropics/skills/tree/main/skills",
}


def is_prunable_dead_url(result: dict) -> bool:
    """Return True only for hard-dead URLs that are safe to prune automatically."""
    return result.get("url_live") is False and result.get("url_status") in HARD_DEAD_URL_STATUSES


def audit_skill(
    skill: dict,
    timeout: int = DEFAULT_TIMEOUT,
    skip_url_check: bool = False,
    skip_desc_fetch: bool = False,
    min_desc_len: int = MIN_DESC_LEN_DEFAULT,
) -> dict:
    """
    Audit a single skill entry. Returns a result dict with:
        name, url, url_live, url_status, desc_stub, desc_reason,
        fetched_desc, fetched_source, action
    """
    name = skill.get("name", "")
    url = skill.get("url", "")
    desc = (skill.get("description") or "").strip()
    source_registry = skill.get("source_registry", "")

    result = {
        "name": name,
        "url": url,
        "source_registry": source_registry,
        "original_desc": desc,
        "url_live": None,
        "url_status": None,
        "desc_stub": False,
        "desc_reason": "",
        "fetched_desc": None,
        "fetched_source": None,
        "action": "ok",
    }

    if not skip_url_check and url:
        live, status = check_url_liveness(url, timeout=timeout)
        result["url_live"] = live
        result["url_status"] = status
        if not live:
            result["action"] = "dead_url"
            debug(f"{name}: dead URL ({status})")

    stub, reason = is_stub_description(desc, min_len=min_desc_len)
    result["desc_stub"] = stub
    result["desc_reason"] = reason

    if stub and result["action"] == "ok":
        result["action"] = "stub_desc"

    if source_registry in NO_LICENSE_DESCRIPTION_SOURCE_REGISTRIES:
        skip_desc_fetch = True

    if stub and not skip_desc_fetch and url:
        fetched, source = fetch_upstream_description(url, timeout=timeout)
        if fetched:
            result["fetched_desc"] = fetched
            result["fetched_source"] = source
            result["action"] = "fixable" if result["action"] in ("stub_desc", "ok") else result["action"]
            debug(f"{name}: fetched description from {source}")
        else:
            debug(f"{name}: could not fetch upstream description")

    return result
