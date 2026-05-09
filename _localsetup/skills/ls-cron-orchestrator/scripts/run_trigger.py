#!/usr/bin/env python3
# Purpose: Run all tasks for a named trigger in sequence (used by generated cron).
# Created: 2026-02-24
# Last updated: 2026-02-24

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

MAX_CMD_LEN = 8192
MAX_TRIGGER_LEN = 128
MAX_TASK_ID_LEN = 128
DEFAULT_TIMEOUT_SECONDS = 3600
MAX_TIMEOUT_SECONDS = 86400


def _sanitize(s: str, max_len: int) -> str:
    if not isinstance(s, str):
        return ""
    out = "".join(c for c in s if ord(c) >= 0x20 and ord(c) != 0x7F)
    out = " ".join(out.split()).strip()
    return out[:max_len] if len(out) > max_len else out


def _contains_shell_operators(command: str) -> bool:
    # We execute with shell=False; reject shell-only operator shapes explicitly.
    return any(token in command for token in ("&&", "||", ";", "|", ">", "<", "`", "\n", "\r"))


def _normalize_command(task: dict) -> tuple[list[str], str | None]:
    raw = task.get("command")
    if isinstance(raw, list):
        argv = [_sanitize(str(part), MAX_CMD_LEN) for part in raw]
        argv = [part for part in argv if part]
        if not argv:
            return [], "command list is empty after sanitization"
        return argv, None
    if not isinstance(raw, str):
        return [], "command must be a string or list"
    cmd = _sanitize(raw, MAX_CMD_LEN)
    if not cmd:
        return [], None
    if _contains_shell_operators(cmd):
        return [], "command contains unsupported shell operators; provide argv list for literal args"
    try:
        argv = shlex.split(cmd, posix=True)
    except ValueError as e:
        return [], f"invalid command quoting: {type(e).__name__}: {e}"
    if not argv:
        return [], "command is empty after parsing"
    return argv, None


def _normalize_timeout(task: dict) -> tuple[int, str | None]:
    value = task.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    try:
        timeout = int(value)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS, f"invalid timeout_seconds: {value!r}"
    if timeout < 1 or timeout > MAX_TIMEOUT_SECONDS:
        return DEFAULT_TIMEOUT_SECONDS, f"timeout_seconds out of bounds (1..{MAX_TIMEOUT_SECONDS}): {timeout}"
    return timeout, None


def main() -> int:
    parser = argparse.ArgumentParser(description="Run tasks for a trigger in sequence.")
    parser.add_argument("--manifest", required=True, help="Path to manifest.yaml")
    parser.add_argument("--repo-root", help="Working directory for commands (default: manifest parent)")
    parser.add_argument("trigger", help="Trigger name")
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    if not manifest_path.is_file():
        print(f"[run_trigger] Not a file: {manifest_path}", file=sys.stderr)
        return 1
    repo_root = Path(args.repo_root).resolve() if args.repo_root else Path.cwd()
    if not repo_root.is_dir():
        print(f"[run_trigger] Not a directory: {repo_root}", file=sys.stderr)
        return 1

    trigger_name = _sanitize(args.trigger, MAX_TRIGGER_LEN)
    if not trigger_name:
        print("[run_trigger] Empty trigger name", file=sys.stderr)
        return 1

    try:
        raw = manifest_path.read_text(encoding="utf-8", errors="replace")
        data = yaml.safe_load(raw)
    except Exception as e:
        print(f"[run_trigger] Failed to load manifest: {e}", file=sys.stderr)
        return 1

    if not isinstance(data, dict):
        print("[run_trigger] Manifest root must be a dict", file=sys.stderr)
        return 1

    triggers = data.get("triggers") or {}
    if trigger_name not in triggers:
        print(f"[run_trigger] Unknown trigger: {trigger_name}", file=sys.stderr)
        return 1

    tasks = [t for t in (data.get("tasks") or []) if isinstance(t, dict)]
    tasks_for_trigger = [t for t in tasks if _sanitize(str(t.get("trigger", "")), MAX_TRIGGER_LEN) == trigger_name and t.get("enabled", True)]
    tasks_for_trigger.sort(key=lambda t: int(t.get("sequence_order", 0)))

    for task in tasks_for_trigger:
        task_id = _sanitize(str(task.get("id", "?")), MAX_TASK_ID_LEN) or "?"
        cmd = task.get("command")
        if isinstance(cmd, str) and len(cmd) > MAX_CMD_LEN:
            print(f"[run_trigger] Task {task.get('id', '?')}: command too long", file=sys.stderr)
            continue
        argv, cmd_error = _normalize_command(task)
        if cmd_error:
            print(f"[run_trigger] Task {task_id}: {cmd_error}", file=sys.stderr)
            return 1
        if not argv:
            continue
        timeout, timeout_error = _normalize_timeout(task)
        if timeout_error:
            print(f"[run_trigger] Task {task_id}: {timeout_error}", file=sys.stderr)
            return 1
        try:
            r = subprocess.run(
                argv,
                shell=False,
                cwd=repo_root,
                env={**os.environ, "LANG": "C"},
                text=True,
                capture_output=True,
                errors="replace",
                timeout=timeout,
            )
            if r.stdout:
                print(r.stdout, end="")
            if r.stderr:
                print(r.stderr, end="", file=sys.stderr)
            if r.returncode != 0:
                print(f"[run_trigger] Task {task_id} exited {r.returncode}", file=sys.stderr)
                return r.returncode
        except subprocess.TimeoutExpired:
            print(f"[run_trigger] Task {task_id} timed out after {timeout}s", file=sys.stderr)
            return 124
        except Exception as e:
            print(f"[run_trigger] Task {task_id}: {type(e).__name__}: {e}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
