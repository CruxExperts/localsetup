#!/usr/bin/env python3
# Purpose: Shared utility helpers for safe mail protocol operations.
# Created: 2026-03-07
# Last updated: 2026-03-07

from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any

CONTROL_CHARS_RE = re.compile(r"[\x00-\x1F\x7F]")


def sanitize_text(value: Any, max_len: int = 512) -> str:
    if value is None:
        return ""
    text = str(value)
    text = CONTROL_CHARS_RE.sub("", text)
    text = " ".join(text.split())
    if len(text) > max_len:
        return text[:max_len]
    return text


def sanitize_list(
    values: Any, item_max_len: int = 128, list_max: int = 500
) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for raw in values[:list_max]:
        item = sanitize_text(raw, item_max_len)
        if item:
            out.append(item)
    return out


def clamp_int(value: Any, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(parsed, max_value))


def as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(value, int):
        return value != 0
    return default


def make_request_id() -> str:
    return uuid.uuid4().hex


def hash_text(value: str, length: int = 16) -> str:
    digest = hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()
    return digest[:length]


def redact_email_header(value: str) -> str:
    clean = sanitize_text(value, 512)
    if not clean:
        return ""
    return hash_text(clean)


def require_fields(payload: dict[str, Any], fields: list[str]) -> list[str]:
    missing: list[str] = []
    for field in fields:
        if field not in payload or payload[field] in ("", None):
            missing.append(field)
    return missing
