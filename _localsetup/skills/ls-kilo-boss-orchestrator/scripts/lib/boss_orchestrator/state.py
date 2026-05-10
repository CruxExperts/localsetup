"""Task, lease, and consensus state management for boss orchestrator."""

from __future__ import annotations

from datetime import datetime, timezone
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

MAX_PATH_ID_LEN = 180


def validate_path_id(value: object, *, field_name: str = "id") -> str:
    """Validate IDs that are used in filesystem path construction."""
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a non-empty string")

    text = value.strip()
    if not text:
        raise ValueError(f"{field_name} must be a non-empty string")
    if len(text) > MAX_PATH_ID_LEN:
        raise ValueError(f"{field_name} must be at most {MAX_PATH_ID_LEN} characters")
    if ".." in text:
        raise ValueError(f"{field_name} must not contain '..'")
    if "/" in text or "\\" in text:
        raise ValueError(f"{field_name} must not contain path separators")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise ValueError(f"{field_name} must not contain control characters")
    return text


class StateStore:
    """File-backed orchestrator state store."""

    def __init__(self, root: Path = STATE_ROOT):
        self.root = root
        ensure_state_dirs(root)
        self.queue_file = root / "queue.jsonl"
        self.events_file = root / "events.log"
        self.deadletter_file = root / "deadletter.jsonl"

    def task_path(self, task_id: str) -> Path:
        safe_task_id = validate_path_id(task_id, field_name="task_id")
        return self.root / "tasks" / f"{safe_task_id}.json"

    def result_path(self, task_id: str) -> Path:
        safe_task_id = validate_path_id(task_id, field_name="task_id")
        return self.root / "results" / f"{safe_task_id}.json"

    def lease_path(self, task_id: str) -> Path:
        safe_task_id = validate_path_id(task_id, field_name="task_id")
        return self.root / "leases" / f"{safe_task_id}.lock"

    def heartbeat_path(self, worker_id: str) -> Path:
        safe_worker_id = validate_path_id(worker_id, field_name="worker_id")
        return self.root / "heartbeats" / f"{safe_worker_id}.json"

    def consensus_path(self, task_id: str) -> Path:
        safe_task_id = validate_path_id(task_id, field_name="task_id")
        return self.root / "consensus" / f"{safe_task_id}.json"

    def session_path(self, session_id: str) -> Path:
        safe_session_id = validate_path_id(session_id, field_name="session_id")
        return self.root / "sessions" / f"{safe_session_id}.json"

    def enqueue(self, task: dict[str, Any]) -> None:
        task_id = validate_path_id(task.get("id"), field_name="task_id")
        task["id"] = task_id
        append_jsonl(self.queue_file, task)
        self.log_event("enqueue", {"task_id": task_id})

    def write_task(self, task: dict[str, Any]) -> None:
        task["updated_at"] = now_iso()
        write_json(self.task_path(str(task["id"])), task)

    def read_task(self, task_id: str) -> dict[str, Any] | None:
        path = self.task_path(task_id)
        if not path.exists():
            return None
        data = load_json(path)
        if isinstance(data, dict):
            data["id"] = task_id
        return data if isinstance(data, dict) else None

    def write_result(self, task_id: str, result: dict[str, Any]) -> None:
        result["updated_at"] = now_iso()
        write_json(self.result_path(task_id), result)

    def read_result(self, task_id: str) -> dict[str, Any] | None:
        path = self.result_path(task_id)
        if not path.exists():
            return None
        data = load_json(path)
        if isinstance(data, dict):
            data["task_id"] = task_id
        return data if isinstance(data, dict) else None

    def claim_lease(self, task_id: str, worker_id: str, ttl_seconds: int) -> bool:
        path = self.lease_path(task_id)
        if path.exists():
            lease = self.read_lease(task_id)
            if lease is not None and self.lease_expired(lease):
                path.unlink()
                self.log_event("lease_reclaim_expired", {"task_id": task_id})
            else:
                return False

        lease = {
            "task_id": task_id,
            "worker_id": worker_id,
            "start_ts": now_iso(),
            "ttl_seconds": int(ttl_seconds),
            "status": "leased",
        }
        write_json(path, lease)
        self.log_event("lease_claim", {"task_id": task_id, "worker_id": worker_id})
        return True

    def read_lease(self, task_id: str) -> dict[str, Any] | None:
        path = self.lease_path(task_id)
        if not path.exists():
            return None
        try:
            data = load_json(path)
        except ValueError:
            return None
        if isinstance(data, dict):
            data["task_id"] = task_id
        return data if isinstance(data, dict) else None

    def lease_expired(self, lease: dict[str, Any]) -> bool:
        try:
            ttl_seconds = int(lease.get("ttl_seconds", 0))
        except (TypeError, ValueError):
            return True
        if ttl_seconds <= 0:
            return True

        raw_start = str(lease.get("start_ts", ""))
        if not raw_start:
            return True
        try:
            started = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
        except ValueError:
            return True
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        age_seconds = (datetime.now(timezone.utc) - started).total_seconds()
        return age_seconds > ttl_seconds

    def reclaim_leases(self) -> dict[str, int]:
        counts = {"invalid": 0, "orphan": 0, "expired": 0}
        for lease_file in sorted((self.root / "leases").glob("*.lock")):
            task_id = lease_file.stem
            try:
                lease = self.read_lease(task_id)
                task = self.read_task(task_id)
            except ValueError as exc:
                invalid_dir = self.root / "deadlettered_leases"
                invalid_dir.mkdir(parents=True, exist_ok=True)
                invalid_path = invalid_dir / f"lease-{datetime.now(timezone.utc).timestamp()}-{lease_file.name}"
                lease_file.replace(invalid_path)
                counts["invalid"] += 1
                self.log_event(
                    "lease_reclaim_invalid",
                    {
                        "task_id": task_id,
                        "path": str(lease_file),
                        "quarantine_file": str(invalid_path),
                        "reason": str(exc),
                    },
                )
                continue
            if lease is None or task is None:
                lease_file.unlink(missing_ok=True)
                counts["orphan"] += 1
                self.log_event("lease_reclaim_orphan", {"task_id": task_id})
                continue
            if not self.lease_expired(lease):
                continue

            attempts = int(task.get("attempts", 0)) + 1
            max_attempts = int(task.get("max_attempts", 3))
            task["attempts"] = attempts
            task["lease_expired_at"] = now_iso()
            if attempts >= max_attempts:
                task["status"] = "failed"
                self.deadletter(task, "lease ttl expired")
            else:
                task["status"] = "pending"
            self.write_task(task)
            lease_file.unlink(missing_ok=True)
            counts["expired"] += 1
            self.log_event(
                "lease_reclaim_expired",
                {"task_id": task_id, "attempts": attempts, "max_attempts": max_attempts},
            )
        return counts

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

    def read_consensus(self, task_id: str) -> dict[str, Any] | None:
        path = self.consensus_path(task_id)
        if not path.exists():
            return None
        data = load_json(path)
        return data if isinstance(data, dict) else None

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
