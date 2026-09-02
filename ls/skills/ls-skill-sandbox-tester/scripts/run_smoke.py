#!/usr/bin/env python3
# Purpose: Run a smoke command inside a skill sandbox and report exit code and output.
# Created: 2026-02-20
# Last updated: 2026-09-02

"""
Run one command with cwd set to a provenance-marked temporary skill copy.
The child receives a minimal environment with sandbox-local home and temp paths.

Usage:
  run_smoke.py --sandbox-dir /path/to/sandbox --command "python3 scripts/pr_review.py --help"

Exit code: same as the command's exit code, or 2 on argument/validation error.
Stdout/stderr from the command are streamed; capture them when invoking from a script.
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

SANDBOX_PATH_MAX = 4096
COMMAND_MAX = 2048
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MARKER_NAME = ".localsetup-sandbox.json"
MARKER_MAX = 16 * 1024
MARKER_SCHEMA_VERSION = 1
INHERITED_ENV_KEYS = (
    "COMSPEC",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "TZ",
    "WINDIR",
)


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _temp_root() -> Path:
    return Path(tempfile.gettempdir()).resolve()


def _reject_symlinks(root: Path) -> None:
    if root.is_symlink():
        raise ValueError(f"sandbox path must not be a symlink: {root}")
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in (*directories, *files):
            candidate = current_path / name
            if candidate.is_symlink():
                raise ValueError(f"sandbox contains a symlink: {candidate}")


def _load_marker(sandbox: Path) -> dict[str, object]:
    marker = sandbox.parent / MARKER_NAME
    if marker.is_symlink() or not marker.is_file():
        raise ValueError(f"sandbox provenance marker is missing or symlinked: {marker}")
    if marker.stat().st_size > MARKER_MAX:
        raise ValueError("sandbox provenance marker exceeds size limit")
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"sandbox provenance marker is invalid: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("sandbox provenance marker must be a JSON object")
    return payload


def _validate_marker(sandbox: Path, payload: dict[str, object]) -> None:
    if payload.get("schema_version") != MARKER_SCHEMA_VERSION:
        raise ValueError("sandbox provenance marker schema is unsupported")
    skill_name = payload.get("skill_name")
    source_value = payload.get("source_dir")
    sandbox_value = payload.get("sandbox_dir")
    fields = (skill_name, source_value, sandbox_value)
    if not all(isinstance(value, str) and value for value in fields):
        raise ValueError("sandbox provenance marker fields are invalid")
    assert isinstance(skill_name, str)
    assert isinstance(source_value, str)
    assert isinstance(sandbox_value, str)
    source = Path(source_value)
    recorded_sandbox = Path(sandbox_value)
    if not source.is_absolute() or not recorded_sandbox.is_absolute():
        raise ValueError("sandbox provenance paths must be absolute")
    source = source.resolve()
    recorded_sandbox = recorded_sandbox.resolve()
    if recorded_sandbox != sandbox:
        raise ValueError("sandbox path does not match provenance marker")
    if source == sandbox or _is_within(source, sandbox.parent):
        raise ValueError("sandbox path resolves to its recorded source")
    if skill_name != sandbox.name or source.name != sandbox.name:
        raise ValueError("sandbox skill name does not match provenance marker")


def _smoke_env(sandbox: Path) -> dict[str, str]:
    env = {
        key: value
        for key in INHERITED_ENV_KEYS
        if (value := os.environ.get(key)) and "\x00" not in value
    }
    runtime_root = sandbox / ".localsetup-runtime"
    home = runtime_root / "home"
    temp = runtime_root / "tmp"
    home.mkdir(parents=True, exist_ok=True)
    temp.mkdir(parents=True, exist_ok=True)
    env.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "TMPDIR": str(temp),
            "TMP": str(temp),
            "TEMP": str(temp),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_DATA_HOME": str(home / ".local" / "share"),
            "XDG_STATE_HOME": str(home / ".local" / "state"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
        }
    )
    return env


def _sanitize_path(value: str, max_len: int = SANDBOX_PATH_MAX) -> Path:
    if not isinstance(value, str) or len(value) > max_len:
        raise ValueError(f"path invalid or length > {max_len}")
    value = value.strip().strip("\x00").strip()
    if not value:
        raise ValueError("sandbox-dir is empty")
    raw = Path(value)
    if raw.is_symlink() or raw.parent.is_symlink():
        raise ValueError(f"sandbox path must not use symlinks: {raw}")
    path = raw.resolve()
    if not path.exists():
        raise ValueError(f"sandbox directory does not exist: {path}")
    if not path.is_dir():
        raise ValueError(f"sandbox path is not a directory: {path}")
    temp_root = _temp_root()
    if path == temp_root or not _is_within(path, temp_root):
        raise ValueError(f"sandbox directory must be within platform temp root: {temp_root}")
    payload = _load_marker(path)
    _validate_marker(path, payload)
    _reject_symlinks(path)
    return path


def _sanitize_command(value: str) -> list[str]:
    if not isinstance(value, str):
        raise ValueError("command must be a string")
    value = value.strip()
    if len(value) > COMMAND_MAX:
        raise ValueError(f"command length exceeds {COMMAND_MAX}")
    if CONTROL_CHARS.search(value):
        raise ValueError("command contains invalid control characters")
    if not value:
        raise ValueError("command is empty")
    try:
        argv = shlex.split(value)
    except ValueError as exc:
        raise ValueError(f"command could not be parsed: {exc}") from exc
    if not argv:
        raise ValueError("command is empty")
    if argv[0] in {"python", "python3"}:
        argv[0] = sys.executable
    return argv


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a smoke command inside a provenance-marked temporary skill copy."
    )
    parser.add_argument(
        "--sandbox-dir",
        metavar="DIR",
        required=True,
        help="Skill-copy path printed by create_sandbox.py; cwd for the command",
    )
    parser.add_argument(
        "--command",
        metavar="CMD",
        required=True,
        help="Command to run (e.g. 'python3 scripts/pr_review.py --help')",
    )
    args = parser.parse_args()

    try:
        sandbox = _sanitize_path(args.sandbox_dir)
        command = _sanitize_command(args.command)
    except ValueError as exc:
        print(f"run_smoke: {exc}", file=sys.stderr)
        return 2

    try:
        result = subprocess.run(
            command,
            cwd=str(sandbox),
            env=_smoke_env(sandbox),
            timeout=300,
        )
        return result.returncode
    except subprocess.TimeoutExpired:
        print("run_smoke: command timed out (300s)", file=sys.stderr)
        return 124
    except OSError as exc:
        print(f"run_smoke: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
