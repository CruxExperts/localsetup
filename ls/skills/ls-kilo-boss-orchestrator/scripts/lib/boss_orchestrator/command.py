"""Command validation for boss-worker task execution."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

MAX_ARG_LEN = 2048
MAX_ARGC = 128
MAX_CMD_LEN = 8192
ALLOWED_COMMAND_PREFIXES = (("kilo", "run"),)


def command_display(argv: list[str]) -> str:
    """Return a log-safe shell-style display string for an already validated argv."""
    return shlex.join(argv)


def _coerce_argv(raw: Any) -> tuple[list[str], str | None]:
    if not isinstance(raw, list):
        return [], "task command must be provided as command_argv YAML list"
    if not raw:
        return [], "command_argv cannot be empty"
    if len(raw) > MAX_ARGC:
        return [], f"command_argv has too many entries (max {MAX_ARGC})"

    argv: list[str] = []
    for index, item in enumerate(raw):
        if not isinstance(item, str):
            return [], f"command_argv[{index}] must be a string"
        if item == "":
            return [], f"command_argv[{index}] cannot be empty"
        if "\x00" in item:
            return [], f"command_argv[{index}] contains a null byte"
        if any(ord(ch) < 0x20 for ch in item):
            return [], f"command_argv[{index}] contains control characters"
        if len(item) > MAX_ARG_LEN:
            return [], f"command_argv[{index}] exceeds {MAX_ARG_LEN} characters"
        argv.append(item)

    if sum(len(item) for item in argv) > MAX_CMD_LEN:
        return [], f"command_argv exceeds {MAX_CMD_LEN} total characters"
    return argv, None


def normalize_command(raw: Any) -> tuple[list[str], str | None]:
    """Validate a task command as structured argv against the Kilo allowlist."""
    argv, error = _coerce_argv(raw)
    if error:
        return [], error

    prefix = (Path(argv[0]).name, argv[1] if len(argv) > 1 else "")
    if prefix not in ALLOWED_COMMAND_PREFIXES:
        allowed = ", ".join(" ".join(item) for item in ALLOWED_COMMAND_PREFIXES)
        return [], f"command_argv must start with one of: {allowed}"

    return argv, None
