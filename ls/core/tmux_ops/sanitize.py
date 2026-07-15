from __future__ import annotations

import re

from .constants import CONTROL_CHARS, MAX_CMD_LEN, MAX_SESSION_NUM, OPS_BASE, SESSION_PATTERN


def _strip_control(s: str) -> str:
    if not s:
        return s
    return CONTROL_CHARS.sub("", s)


def _ops_session_sequence() -> list[str]:
    return [OPS_BASE] + [f"{OPS_BASE}{i}" for i in range(1, MAX_SESSION_NUM + 1)]


def _sanitize_session(name: str) -> str | None:
    if not name or not isinstance(name, str):
        return None
    s = _strip_control(name.strip())
    if len(s) > 32 or SESSION_PATTERN.fullmatch(s) is None:
        return None
    return s


def _sanitize_command(raw: str) -> tuple[str | None, str | None]:
    if not raw or not isinstance(raw, str):
        return None, "empty or non-string command"
    s = _strip_control(raw.strip())
    if not s:
        return None, "command empty after sanitization"
    if len(s) > MAX_CMD_LEN:
        return None, f"command exceeds max length {MAX_CMD_LEN} (got {len(s)})"
    return s, None


def _compile_idle_re(pattern_str: str | None) -> tuple[re.Pattern[str] | None, str | None]:
    if pattern_str is None:
        return None, None
    try:
        return re.compile(pattern_str), None
    except re.error as e:
        return None, f"invalid regex {pattern_str!r}: {e}"
