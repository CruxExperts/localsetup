#!/usr/bin/env python3
# Purpose: Run pre_ship_checks from manifest or CLI before ship (spec Part 12).
# Created: 2026-03-09
# Last updated: 2026-03-09

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Any

_ALLOWED_EXECUTABLES = {"python3", "pytest"}
_SHELL_METACHARS = set("&;|<>`$(){}")
_MAX_TIMEOUT_SECONDS = 600


def _command_error(message: str, cmd: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "code": "PRE_SHIP_CHECK_REJECTED",
        "error": message,
        "failed_cmd": str(cmd)[:500],
    }


def _normalize_check(check: Any) -> tuple[list[str], int, str] | dict[str, Any]:
    timeout = _MAX_TIMEOUT_SECONDS
    original = check
    if isinstance(check, str):
        if any(char in _SHELL_METACHARS for char in check):
            return _command_error("pre_ship_checks string contains shell metacharacters", check)
        try:
            argv = shlex.split(check)
        except ValueError as exc:
            return _command_error(f"pre_ship_checks string is not parseable: {exc}", check)
    elif isinstance(check, list):
        argv = check
    elif isinstance(check, dict):
        argv = check.get("argv")
        raw_timeout = check.get("timeout_seconds", timeout)
        if not isinstance(raw_timeout, int) or raw_timeout < 1 or raw_timeout > _MAX_TIMEOUT_SECONDS:
            return _command_error("pre_ship_checks timeout_seconds must be 1..600", check)
        timeout = raw_timeout
    else:
        return _command_error("pre_ship_checks entries must be strings, argv lists, or objects", check)

    if not isinstance(argv, list) or not argv:
        return _command_error("pre_ship_checks argv must be a non-empty list", original)
    if not all(isinstance(part, str) and part and "\x00" not in part for part in argv):
        return _command_error("pre_ship_checks argv entries must be non-empty strings", original)

    exe = Path(argv[0]).name
    if exe not in _ALLOWED_EXECUTABLES:
        allowed = ", ".join(sorted(_ALLOWED_EXECUTABLES))
        return _command_error(f"pre_ship_checks executable must be one of: {allowed}", original)
    if exe == "python3":
        python_args = argv[1:]
        runs_pytest = len(python_args) >= 2 and python_args[:2] == ["-m", "pytest"]
        checks_version = python_args in (["--version"], ["-V"])
        if not (runs_pytest or checks_version):
            return _command_error(
                "pre_ship_checks python3 commands may only run --version or -m pytest",
                original,
            )
    return argv, timeout, " ".join(shlex.quote(part) for part in argv)


def run_pre_ship_checks(
    manifest: dict[str, Any],
    *,
    cwd: Path | None = None,
) -> dict[str, Any]:
    """
    If manifest has pre_ship_checks, run allowed argv checks; all must exit 0.
    Returns {ok: bool, results: [{cmd, returncode, stdout, stderr}]}.
    """
    checks = manifest.get("pre_ship_checks")
    if not checks:
        return {"ok": True, "results": [], "skipped": True}
    if not isinstance(checks, list):
        return {"ok": False, "error": "pre_ship_checks must be a list"}
    results = []
    cwd = str(cwd) if cwd else None
    for check in checks:
        normalized = _normalize_check(check)
        if isinstance(normalized, dict):
            return normalized | {"results": results}
        argv, timeout, display_cmd = normalized
        try:
            r = subprocess.run(
                argv,
                shell=False,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except OSError as exc:
            results.append(
                {
                    "cmd": display_cmd[:500],
                    "returncode": None,
                    "stdout": "",
                    "stderr": str(exc)[:2000],
                }
            )
            return {"ok": False, "results": results, "failed_cmd": display_cmd[:500]}
        except subprocess.TimeoutExpired as exc:
            results.append(
                {
                    "cmd": display_cmd[:500],
                    "returncode": None,
                    "stdout": (exc.stdout or "")[:2000],
                    "stderr": f"pre_ship_check timed out after {timeout}s",
                }
            )
            return {
                "ok": False,
                "code": "PRE_SHIP_CHECK_TIMEOUT",
                "results": results,
                "failed_cmd": display_cmd[:500],
            }
        results.append(
            {
                "cmd": display_cmd[:500],
                "returncode": r.returncode,
                "stdout": (r.stdout or "")[:2000],
                "stderr": (r.stderr or "")[:2000],
            }
        )
        if r.returncode != 0:
            return {"ok": False, "results": results, "failed_cmd": display_cmd[:500]}
    return {"ok": True, "results": results}
