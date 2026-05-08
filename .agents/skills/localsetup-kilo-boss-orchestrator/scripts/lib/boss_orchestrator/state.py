"""Task, lease, and consensus state management for boss orchestrator."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .util import (
    STATE_ROOT,
    append_jsonl,
    ensure_state_dirs,
    load_json,
    now_iso,
    write_json,
)


class StateStore:
    """File-backed orchestrator state store."""

    def __init__(self, root: Path = STATE_ROOT):
        self.root = root
        ensure_state_dirs(root)
        self.queue_file = root / "queue.jsonl"
        self.events_file = root / "events.log"
        self.deadletter_file = root / "deadletter.jsonl"

    def task_path(self, task_id: str) -> Path:
        return self.root / "tasks" / f"{task_id}.json"

    def result_path(self, task_id: str) -> Path:
        return self.root / "results" / f"{task_id}.json"

    def lease_path(self, task_id: str) -> Path:
        return self.root / "leases" / f"{task_id}.lock"

    def heartbeat_path(self, worker_id: str) -> Path:
        return self.root / "heartbeats" / f"{worker_id}.json"

    def consensus_path(self, task_id: str) -> Path:
        return self.root / "consensus" / f"{task_id}.json"

    def session_path(self, session_id: str) -> Path:
        return self.root / "sessions" / f"{session_id}.json"

    def enqueue(self, task: dict[str, Any]) -> None:
        append_jsonl(self.queue_file, task)
        self.log_event("enqueue", {"task_id": task.get("id")})

    def write_task(self, task: dict[str, Any]) -> None:
        task["updated_at"] = now_iso()
        write_json(self.task_path(str(task["id"])), task)

    def read_task(self, task_id: str) -> dict[str, Any] | None:
        path = self.task_path(task_id)
        if not path.exists():
            return None
        data = load_json(path)
        return data if isinstance(data, dict) else None

    def write_result(self, task_id: str, result: dict[str, Any]) -> None:
        result["updated_at"] = now_iso()
        write_json(self.result_path(task_id), result)

    def read_result(self, task_id: str) -> dict[str, Any] | None:
        path = self.result_path(task_id)
        if not path.exists():
            return None
        data = load_json(path)
        return data if isinstance(data, dict) else None

    def claim_lease(self, task_id: str, worker_id: str, ttl_seconds: int) -> bool:
        lease = {
            "task_id": task_id,
            "worker_id": worker_id,
            "start_ts": now_iso(),
            "ttl_seconds": int(ttl_seconds),
            "status": "leased",
        }
        path = self.lease_path(task_id)
        if path.exists():
            return False
        write_json(path, lease)
        self.log_event("lease_claim", {"task_id": task_id, "worker_id": worker_id})
        return True

    def release_lease(self, task_id: str) -> None:
        path = self.lease_path(task_id)
        if path.exists():
            path.unlink()
            self.log_event("lease_release", {"task_id": task_id})

    def write_heartbeat(self, worker_id: str, payload: dict[str, Any]) -> None:
        payload = dict(payload)
        payload["worker_id"] = worker_id
        payload["last_seen"] = now_iso()
        write_json(self.heartbeat_path(worker_id), payload)

    def write_consensus(self, task_id: str, payload: dict[str, Any]) -> None:
        payload = dict(payload)
        payload["task_id"] = task_id
        payload["decided_at"] = now_iso()
        write_json(self.consensus_path(task_id), payload)

    def write_session(self, session_id: str, payload: dict[str, Any]) -> None:
        body = dict(payload)
        body["session_id"] = session_id
        body["updated_at"] = now_iso()
        write_json(self.session_path(session_id), body)

    def read_session(self, session_id: str) -> dict[str, Any] | None:
        path = self.session_path(session_id)
        if not path.exists():
            return None
        data = load_json(path)
        return data if isinstance(data, dict) else None

    def deadletter(self, task: dict[str, Any], reason: str) -> None:
        event = {"task": task, "reason": reason, "ts": now_iso()}
        append_jsonl(self.deadletter_file, event)
        self.log_event("deadletter", {"task_id": task.get("id"), "reason": reason})

    def log_event(self, event: str, payload: dict[str, Any]) -> None:
        append_jsonl(
            self.events_file,
            {
                "ts": now_iso(),
                "event": event,
                "payload": payload,
            },
        )
