#!/usr/bin/env python3
"""Headless Kilo worker runner for boss orchestrator task cards."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
from deps import require_deps  # noqa: E402

require_deps(["yaml"])

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.boss_orchestrator.state import StateStore  # noqa: E402
from lib.boss_orchestrator.util import now_iso  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[4]
ROUTER_SCRIPT = REPO_ROOT / "scripts" / "ops" / "agent_failure_backoff_router.py"
MAX_CMD_LEN = 8192
MAX_TIMEOUT_SECONDS = 86400


def _safe_task_id(raw: str) -> str:
    if not raw or any(ch in raw for ch in ["/", "..", "\\"]):
        raise ValueError("invalid task id")
    return raw


def _sanitize(value: object, max_len: int = MAX_CMD_LEN) -> str:
    text = str(value)
    cleaned = "".join(ch for ch in text if ord(ch) >= 0x20 and ord(ch) != 0x7F)
    cleaned = " ".join(cleaned.split()).strip()
    return cleaned[:max_len] if len(cleaned) > max_len else cleaned


def _contains_shell_operators(command: str) -> bool:
    return any(
        token in command for token in ("&&", "||", ";", "|", ">", "<", "`", "\n", "\r")
    )


def _normalize_command(raw: object) -> tuple[list[str], str | None]:
    if isinstance(raw, list):
        argv = [_sanitize(part) for part in raw]
        argv = [part for part in argv if part]
        if not argv:
            return [], "command list is empty after sanitization"
        return argv, None

    if not isinstance(raw, str):
        return [], "task command must be a string or argv list"
    command = _sanitize(raw)
    if not command:
        return [], "task command missing"
    if _contains_shell_operators(command):
        return [], "task command contains unsupported shell operators; provide argv list for literal args"
    try:
        argv = shlex.split(command, posix=True)
    except ValueError as exc:
        return [], f"invalid task command quoting: {type(exc).__name__}: {exc}"
    if not argv:
        return [], "task command is empty after parsing"
    return argv, None


def _normalize_timeout(raw: object) -> tuple[int, str | None]:
    try:
        timeout = int(raw)
    except (TypeError, ValueError):
        return 600, f"invalid timeout_seconds: {raw!r}"
    if timeout < 1 or timeout > MAX_TIMEOUT_SECONDS:
        return 600, f"timeout_seconds out of bounds (1..{MAX_TIMEOUT_SECONDS}): {timeout}"
    return timeout, None


def _result_base(
    *,
    task_id: str,
    worker_id: str,
    session_id: str,
    session: dict,
    task: dict,
    started: str,
) -> dict:
    return {
        "task_id": task_id,
        "worker_id": worker_id,
        "session_id": session_id,
        "session_shared": bool(session.get("session_shared", True)),
        "session_visibility": str(
            session.get("session_visibility", "shared-authenticated")
        ),
        "role": task.get("role", "worker"),
        "files_changed": [],
        "started_at": started,
        "completed_at": now_iso(),
    }


def _report_router(
    *,
    worker_id: str,
    task_id: str,
    session_id: str,
    command: str,
    exit_code: int,
    stdout: str,
    stderr: str,
    ok: bool,
) -> None:
    if not ROUTER_SCRIPT.exists():
        return

    base = [
        "python3",
        str(ROUTER_SCRIPT),
        "--state-root",
        str(REPO_ROOT / ".kilo" / "state"),
    ]
    if ok:
        cmd = base + [
            "report-success",
            "--agent-role",
            worker_id,
            "--operation",
            f"boss-task:{task_id}:session:{session_id}",
        ]
    else:
        cmd = base + [
            "report-failure",
            "--agent-role",
            worker_id,
            "--operation",
            f"boss-task:{task_id}:session:{session_id}",
            "--command",
            command,
            "--exit-code",
            str(exit_code),
            "--stdout",
            stdout[-3000:],
            "--stderr",
            stderr[-3000:],
            "--extra-json",
            '{"source":"kilo_headless_runner"}',
        ]
    subprocess.run(cmd, check=False, capture_output=True, text=True)


def run_worker(task_id: str, worker_id: str, session_id: str) -> int:
    store = StateStore()
    task = store.read_task(task_id)
    session = store.read_session(session_id) or {}
    if task is None:
        print(f"[worker] task not found: {task_id}", file=sys.stderr)
        return 1

    command_raw = task.get("command", "")
    command_argv, command_error = _normalize_command(command_raw)
    if command_error:
        print(f"[worker] {command_error}", file=sys.stderr)
        return 1

    repo_root = str(task.get("repo_root", "."))
    timeout_seconds, timeout_error = _normalize_timeout(task.get("timeout_seconds", 600))
    if timeout_error:
        print(f"[worker] {timeout_error}", file=sys.stderr)
        return 1

    store.write_heartbeat(worker_id, {"current_task": task_id, "status": "running"})

    env = dict(os.environ)
    env["KILO_NO_INTERACTIVE"] = "1"
    env["KILO_SHARED_SESSION_ID"] = session_id
    env["KILO_SESSION_SHARED"] = (
        "1" if bool(session.get("session_shared", True)) else "0"
    )

    started = now_iso()
    try:
        proc = subprocess.run(
            command_argv,
            shell=False,
            cwd=repo_root,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout_seconds,
            env=env,
        )
        status = "completed" if proc.returncode == 0 else "failed"
        result = {
            **_result_base(
                task_id=task_id,
                worker_id=worker_id,
                session_id=session_id,
                session=session,
                task=task,
                started=started,
            ),
            "status": status,
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
        store.write_result(task_id, result)
        store.write_heartbeat(worker_id, {"current_task": None, "status": "idle"})
        _report_router(
            worker_id=worker_id,
            task_id=task_id,
            session_id=session_id,
            command=" ".join(command_argv),
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            ok=(status == "completed"),
        )
        return 0 if status == "completed" else 2
    except (OSError, ValueError) as exc:
        error_text = f"{type(exc).__name__}: {exc}"
        result = {
            **_result_base(
                task_id=task_id,
                worker_id=worker_id,
                session_id=session_id,
                session=session,
                task=task,
                started=started,
            ),
            "status": "failed",
            "exit_code": 1,
            "stdout": "",
            "stderr": error_text,
        }
        store.write_result(task_id, result)
        store.write_heartbeat(worker_id, {"current_task": None, "status": "failed"})
        _report_router(
            worker_id=worker_id,
            task_id=task_id,
            session_id=session_id,
            command=" ".join(command_argv),
            exit_code=1,
            stdout="",
            stderr=error_text,
            ok=False,
        )
        return 1
    except subprocess.TimeoutExpired:
        result = {
            **_result_base(
                task_id=task_id,
                worker_id=worker_id,
                session_id=session_id,
                session=session,
                task=task,
                started=started,
            ),
            "status": "timed_out",
            "exit_code": 124,
            "stdout": "",
            "stderr": f"timed out after {timeout_seconds}s",
        }
        store.write_result(task_id, result)
        store.write_heartbeat(worker_id, {"current_task": None, "status": "timed_out"})
        _report_router(
            worker_id=worker_id,
            task_id=task_id,
            session_id=session_id,
            command=" ".join(command_argv),
            exit_code=124,
            stdout="",
            stderr=f"timed out after {timeout_seconds}s",
            ok=False,
        )
        return 124


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a boss orchestrator worker task")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--session-id", required=True)
    args = parser.parse_args()

    task_id = _safe_task_id(args.task_id)
    worker_id = _safe_task_id(args.worker_id)
    session_id = _safe_task_id(args.session_id)
    return run_worker(task_id, worker_id, session_id)


if __name__ == "__main__":
    raise SystemExit(main())
