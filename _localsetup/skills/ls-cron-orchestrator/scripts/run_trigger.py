#!/usr/bin/env python3
# Purpose: Run all tasks for a named trigger in sequence (used by generated cron).
# Created: 2026-02-24
# Last updated: 2026-02-24

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from _cron_manifest import (
    MAX_DELAY_SECONDS,
    MAX_TRIGGER_LEN,
    ManifestError,
    clean_display,
    load_manifest,
    normalize_delay_seconds,
    validate_identifier,
    validate_manifest,
)


def _load_validated_manifest(manifest_path: Path) -> dict:
    try:
        return validate_manifest(load_manifest(manifest_path))
    except ManifestError as exc:
        print(f"[run_trigger] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Run tasks for a trigger in sequence.")
    parser.add_argument("--manifest", required=True, help="Path to manifest.yaml")
    parser.add_argument("--repo-root", help="Working directory for commands (default: manifest parent)")
    parser.add_argument(
        "--delay-seconds",
        default=0,
        help=f"Delay execution before running tasks, for @reboot cron entries (0..{MAX_DELAY_SECONDS})",
    )
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

    try:
        trigger_name = validate_identifier(args.trigger, "trigger", MAX_TRIGGER_LEN)
        delay_seconds = normalize_delay_seconds(args.delay_seconds, "delay_seconds")
    except ManifestError as exc:
        print(f"[run_trigger] {exc}", file=sys.stderr)
        return 1
    if delay_seconds:
        time.sleep(delay_seconds)

    data = _load_validated_manifest(manifest_path)

    triggers = data.get("triggers") or {}
    if trigger_name not in triggers:
        print(f"[run_trigger] Unknown trigger: {trigger_name}", file=sys.stderr)
        return 1

    tasks = data.get("tasks") or []
    tasks_for_trigger = [task for task in tasks if task["trigger"] == trigger_name and task["enabled"]]
    tasks_for_trigger.sort(key=lambda task: task["sequence_order"])

    for task in tasks_for_trigger:
        task_id = clean_display(task["id"], 128)
        argv = task["argv"]
        timeout = task["timeout_seconds"]
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
