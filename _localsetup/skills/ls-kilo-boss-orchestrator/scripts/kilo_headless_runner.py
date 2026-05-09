#!/usr/bin/env python3
"""Headless Kilo worker runner for boss orchestrator task cards."""

from __future__ import annotations

import argparse
import os
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


def _safe_task_id(raw: str) -> str:
    if not raw or any(ch in raw for ch in ["/", "..", "\\"]):
        raise ValueError("invalid task id")
    return raw


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

    command = str(task.get("command", "")).strip()
    if not command:
        print("[worker] task command missing", file=sys.stderr)
        return 1

    repo_root = str(task.get("repo_root", "."))
    timeout_seconds = int(task.get("timeout_seconds", 600))

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
            command,
            shell=True,
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
        )
        status = "completed" if proc.returncode == 0 else "failed"
        result = {
            "task_id": task_id,
            "worker_id": worker_id,
            "session_id": session_id,
            "session_shared": bool(session.get("session_shared", True)),
            "session_visibility": str(
                session.get("session_visibility", "shared-authenticated")
            ),
            "role": task.get("role", "worker"),
            "status": status,
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "files_changed": [],
            "started_at": started,
            "completed_at": now_iso(),
        }
        store.write_result(task_id, result)
        store.write_heartbeat(worker_id, {"current_task": None, "status": "idle"})
        _report_router(
            worker_id=worker_id,
            task_id=task_id,
            session_id=session_id,
            command=command,
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            ok=(status == "completed"),
        )
        return 0 if status == "completed" else 2
    except subprocess.TimeoutExpired:
        result = {
            "task_id": task_id,
            "worker_id": worker_id,
            "session_id": session_id,
            "session_shared": bool(session.get("session_shared", True)),
            "session_visibility": str(
                session.get("session_visibility", "shared-authenticated")
            ),
            "role": task.get("role", "worker"),
            "status": "timed_out",
            "exit_code": 124,
            "stdout": "",
            "stderr": f"timed out after {timeout_seconds}s",
            "files_changed": [],
            "started_at": started,
            "completed_at": now_iso(),
        }
        store.write_result(task_id, result)
        store.write_heartbeat(worker_id, {"current_task": None, "status": "timed_out"})
        _report_router(
            worker_id=worker_id,
            task_id=task_id,
            session_id=session_id,
            command=command,
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
