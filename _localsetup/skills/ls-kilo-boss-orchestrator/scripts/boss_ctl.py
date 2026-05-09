#!/usr/bin/env python3
"""Boss control plane for Kilo headless boss-worker orchestration."""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
from deps import require_deps  # noqa: E402

require_deps(["yaml"])

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.boss_orchestrator.command import command_display, normalize_command  # noqa: E402
from lib.boss_orchestrator.consensus import consensus_verdict  # noqa: E402
from lib.boss_orchestrator.state import StateStore  # noqa: E402
from lib.boss_orchestrator.util import now_iso, load_yaml, sanitize_path  # noqa: E402


def cmd_init(_: argparse.Namespace) -> int:
    store = StateStore()
    store.log_event("init", {"msg": "orchestrator state initialized"})
    print("[OK] orchestrator state initialized at .kilo/state/orchestrator")
    return 0


def _task_from_template(template_path: str) -> dict:
    payload = load_yaml(sanitize_path(template_path))
    if not isinstance(payload, dict):
        raise ValueError("task template must be a YAML object")
    return payload


def cmd_enqueue(args: argparse.Namespace) -> int:
    store = StateStore()
    template = _task_from_template(args.task_file)

    task_id = str(template.get("id") or f"task-{uuid.uuid4().hex[:12]}")
    session_id = str(template.get("session_id", "")).strip()
    if not session_id:
        raise ValueError("task template must include non-empty session_id")

    session_visibility = str(
        template.get("session_visibility", "shared-authenticated")
    ).strip()
    if not session_visibility:
        raise ValueError("session_visibility cannot be empty")

    command_argv, command_error = normalize_command(
        template.get("command_argv", template.get("command"))
    )
    if command_error:
        raise ValueError(command_error)

    task = {
        "id": task_id,
        "status": "pending",
        "priority": int(template.get("priority", 100)),
        "attempts": int(template.get("attempts", 0)),
        "max_attempts": int(template.get("max_attempts", 3)),
        "command_argv": command_argv,
        "command": command_display(command_argv),
        "repo_root": str(template.get("repo_root", ".")),
        "timeout_seconds": int(template.get("timeout_seconds", 600)),
        "destructive": bool(template.get("destructive", False)),
        "consensus_required": bool(template.get("consensus_required", True)),
        "worker_primary": str(template.get("worker_primary", "worker-primary")),
        "worker_verifier": str(template.get("worker_verifier", "worker-verifier")),
        "session_id": session_id,
        "session_shared": bool(template.get("session_shared", True)),
        "session_visibility": session_visibility,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }

    store.enqueue(task)
    store.write_task(task)
    print(f"[OK] enqueued task {task_id}")
    return 0


def _spawn_worker_task(task_id: str, worker_id: str, session_id: str) -> None:
    import subprocess

    script_root = Path(__file__).resolve().parent
    cmd: list[str] = [
        "python3",
        "scripts/kilo_headless_runner.py",
        "--task-id",
        str(task_id),
        "--worker-id",
        str(worker_id),
        "--session-id",
        str(session_id),
    ]
    try:
        result = subprocess.run(
            cmd,
            check=False,
            cwd=str(script_root),
            shell=False,
            capture_output=True,
            text=True,
            errors="replace",
        )
        if result.returncode != 0:
            joined = " ".join(cmd)
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            detail = stderr or stdout or "no subprocess output"
            raise RuntimeError(
                f"worker task '{task_id}' exited {result.returncode} via '{joined}': {detail}"
            )
    except OSError as exc:
        joined = " ".join(cmd)
        raise RuntimeError(
            f"failed to spawn worker task '{task_id}' via '{joined}': {type(exc).__name__}: {exc}"
        ) from exc


def cmd_dispatch(args: argparse.Namespace) -> int:
    store = StateStore()
    tasks_dir = store.root / "tasks"

    dispatched = 0
    for task_file in sorted(tasks_dir.glob("*.json")):
        task = store.read_task(task_file.stem)
        if not task or task.get("status") != "pending":
            continue
        if dispatched >= args.max_dispatch:
            break

        task_id = str(task["id"])
        if not store.claim_lease(
            task_id, "boss", ttl_seconds=task.get("timeout_seconds", 600)
        ):
            continue

        task["status"] = "running"
        task["updated_at"] = now_iso()
        store.write_task(task)

        primary_task = dict(task)
        primary_task["id"] = f"{task_id}-primary"
        primary_task["role"] = "primary"
        store.write_task(primary_task)

        verifier_task = dict(task)
        verifier_task["id"] = f"{task_id}-verifier"
        verifier_task["role"] = "verifier"
        store.write_task(verifier_task)

        session_id = str(task.get("session_id", f"session-{task_id}"))
        store.write_session(
            session_id,
            {
                "task_id": task_id,
                "session_shared": bool(task.get("session_shared", True)),
                "session_visibility": str(
                    task.get("session_visibility", "shared-authenticated")
                ),
                "workers": [
                    str(task.get("worker_primary", "worker-primary")),
                    str(task.get("worker_verifier", "worker-verifier")),
                ],
                "status": "running",
                "discovered_at": now_iso(),
            },
        )

        try:
            _spawn_worker_task(primary_task["id"], task["worker_primary"], session_id)
            _spawn_worker_task(verifier_task["id"], task["worker_verifier"], session_id)
        except RuntimeError as exc:
            task["status"] = "failed"
            task["updated_at"] = now_iso()
            store.write_task(task)
            store.release_lease(task_id)
            store.deadletter(task, str(exc))
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1

        dispatched += 1
        store.log_event("dispatch", {"task_id": task_id})

    print(f"[OK] dispatched {dispatched} task(s)")
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    store = StateStore()
    total = 0
    for task_file in sorted((store.root / "tasks").glob("*.json")):
        task = store.read_task(task_file.stem)
        if not task:
            continue
        total += 1
        print(f"{task.get('id')}: {task.get('status')}")
    if total == 0:
        print("no tasks found")
    return 0


def cmd_consensus(args: argparse.Namespace) -> int:
    store = StateStore()
    base_id = args.task_id
    primary = store.read_result(f"{base_id}-primary")
    verifier = store.read_result(f"{base_id}-verifier")

    if not primary or not verifier:
        print("[ERROR] missing primary or verifier result", file=sys.stderr)
        return 1

    verdict = consensus_verdict(primary, verifier)
    store.write_consensus(base_id, verdict)

    if verdict["gate_passed"]:
        print("[OK] consensus gate passed")
        return 0

    print(f"[WARN] consensus mismatch severity={verdict['severity']}")
    if verdict["requires_tiebreaker"]:
        print("[WARN] tiebreaker required")
        return 2
    return 1


def cmd_finalize(args: argparse.Namespace) -> int:
    store = StateStore()
    task = store.read_task(args.task_id)
    if not task:
        print("[ERROR] task not found", file=sys.stderr)
        return 1

    consensus = store.read_consensus(args.task_id)
    if consensus is None:
        print("[ERROR] consensus verdict missing", file=sys.stderr)
        return 1
    if consensus.get("requires_tiebreaker") is True:
        print("[ERROR] consensus requires tiebreaker; refusing finalize", file=sys.stderr)
        return 2
    if consensus.get("gate_passed") is not True:
        print("[ERROR] consensus gate did not pass; refusing finalize", file=sys.stderr)
        return 2

    task["status"] = "done"
    task["completed_at"] = now_iso()
    store.write_task(task)
    store.release_lease(args.task_id)
    store.log_event("finalize", {"task_id": args.task_id})
    print(f"[OK] finalized {args.task_id}")
    return 0


def cmd_watchdog(_: argparse.Namespace) -> int:
    store = StateStore()
    reclaimed = store.reclaim_leases()
    print(
        "[OK] watchdog reclaimed "
        f"{reclaimed['orphan']} orphan lease(s), "
        f"{reclaimed['expired']} expired lease(s)"
    )
    return 0


def cmd_write_validation(args: argparse.Namespace) -> int:
    validation_dir = Path(".kilo/state/validation")
    validation_dir.mkdir(parents=True, exist_ok=True)
    path = validation_dir / f"{args.task_id}.md"
    content = f"""# Validation Record: {args.task_id}\n\n- Timestamp: {now_iso()}\n- Outcome: {args.outcome}\n- Notes: {args.notes}\n"""
    path.write_text(content, encoding="utf-8")
    print(f"[OK] wrote validation record {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kilo boss orchestrator control")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="initialize orchestrator state").set_defaults(
        func=cmd_init
    )

    enqueue = sub.add_parser("enqueue", help="enqueue task from YAML template")
    enqueue.add_argument("--task-file", required=True)
    enqueue.set_defaults(func=cmd_enqueue)

    dispatch = sub.add_parser("dispatch", help="dispatch pending tasks")
    dispatch.add_argument("--max-dispatch", type=int, default=1)
    dispatch.set_defaults(func=cmd_dispatch)

    sub.add_parser("status", help="show task status").set_defaults(func=cmd_status)

    consensus = sub.add_parser("consensus", help="evaluate primary vs verifier")
    consensus.add_argument("--task-id", required=True)
    consensus.set_defaults(func=cmd_consensus)

    finalize = sub.add_parser("finalize", help="finalize task after consensus")
    finalize.add_argument("--task-id", required=True)
    finalize.set_defaults(func=cmd_finalize)

    sub.add_parser("watchdog", help="reclaim orphan and expired leases").set_defaults(
        func=cmd_watchdog
    )

    write_val = sub.add_parser("write-validation", help="write validation record")
    write_val.add_argument("--task-id", required=True)
    write_val.add_argument("--outcome", required=True)
    write_val.add_argument("--notes", default="")
    write_val.set_defaults(func=cmd_write_validation)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
