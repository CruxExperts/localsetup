"""
Purpose: On-disk job registry for long-running Scrapling operations.
Created: 2026-03-16
Last Updated: 2026-03-16
"""

from __future__ import annotations

import json
import os
import signal
from dataclasses import asdict, dataclass, field
from json import JSONDecodeError
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import ScraplingConfig


@dataclass
class JobRecord:
    job_id: str
    kind: str
    status: str
    created_at: str
    updated_at: str
    command: List[str]
    workdir: str
    pid: Optional[int] = None
    output_path: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class JobRegistryError(Exception):
    """Raised when a persisted job record exists but cannot be decoded."""

    def __init__(self, path: Path, reason: str, message: str) -> None:
        super().__init__(message)
        self.path = path
        self.reason = reason

    def as_dict(self) -> Dict[str, Any]:
        return {
            "reason": self.reason,
            "path": str(self.path),
            "error": str(self),
            "error_type": type(self).__name__,
        }


def _jobs_dir(cfg: ScraplingConfig) -> Path:
    # Prefer cache_dir so jobs are contained under the framework tree.
    jobs_root = cfg.cache_dir / "jobs"
    jobs_root.mkdir(parents=True, exist_ok=True)
    scrapling_jobs = jobs_root / "scrapling"
    scrapling_jobs.mkdir(parents=True, exist_ok=True)
    return scrapling_jobs


def _job_path(cfg: ScraplingConfig, job_id: str) -> Path:
    return _jobs_dir(cfg) / f"{job_id}.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_from_data(path: Path, data: Any) -> JobRecord:
    if not isinstance(data, dict):
        raise JobRegistryError(path, "registry_entry_invalid", "job registry entry must be a JSON object")

    required = ("job_id", "kind", "status", "created_at", "updated_at")
    missing = [key for key in required if key not in data]
    if missing:
        missing_text = ", ".join(missing)
        raise JobRegistryError(
            path,
            "registry_entry_invalid",
            f"job registry entry is missing required field(s): {missing_text}",
        )

    command = data.get("command", [])
    if not isinstance(command, list):
        raise JobRegistryError(path, "registry_entry_invalid", "job registry field 'command' must be a list")

    metadata = data.get("metadata", {})
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise JobRegistryError(path, "registry_entry_invalid", "job registry field 'metadata' must be an object")

    pid = data.get("pid")
    if pid is not None and not isinstance(pid, int):
        raise JobRegistryError(path, "registry_entry_invalid", "job registry field 'pid' must be an integer")

    return JobRecord(
        job_id=str(data["job_id"]),
        kind=str(data["kind"]),
        status=str(data["status"]),
        created_at=str(data["created_at"]),
        updated_at=str(data["updated_at"]),
        command=[str(part) for part in command],
        workdir=str(data.get("workdir", "")),
        pid=pid,
        output_path=data.get("output_path"),
        error=data.get("error"),
        metadata=metadata,
    )


def _read_job_record(path: Path) -> JobRecord:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except JSONDecodeError as exc:
        raise JobRegistryError(
            path,
            "registry_entry_malformed_json",
            f"malformed job registry JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}",
        ) from exc
    except OSError as exc:
        raise JobRegistryError(path, "registry_entry_unreadable", str(exc)) from exc
    return _record_from_data(path, data)


def create_job(cfg: ScraplingConfig, job: JobRecord) -> JobRecord:
    path = _job_path(cfg, job.job_id)
    if path.exists():
        # Overwrite for now; callers should use unique job_ids.
        pass
    path.write_text(json.dumps(asdict(job), indent=2), encoding="utf-8")
    return job


def load_job(cfg: ScraplingConfig, job_id: str) -> Optional[JobRecord]:
    path = _job_path(cfg, job_id)
    if not path.exists():
        return None
    return _read_job_record(path)


def list_jobs_with_errors(cfg: ScraplingConfig, kind: Optional[str] = None) -> Tuple[List[JobRecord], List[Dict[str, Any]]]:
    jobs: List[JobRecord] = []
    errors: List[Dict[str, Any]] = []
    jobs_dir = _jobs_dir(cfg)
    for path in jobs_dir.glob("*.json"):
        try:
            record = _read_job_record(path)
        except JobRegistryError as exc:
            errors.append(exc.as_dict())
            continue
        if kind is None or record.kind == kind:
            jobs.append(record)
    return jobs, errors


def list_jobs(cfg: ScraplingConfig, kind: Optional[str] = None) -> List[JobRecord]:
    jobs, _errors = list_jobs_with_errors(cfg, kind=kind)
    return jobs


def update_job(cfg: ScraplingConfig, job: JobRecord, **changes: Any) -> JobRecord:
    for key, value in changes.items():
        setattr(job, key, value)
    job.updated_at = _utc_now_iso()
    path = _job_path(cfg, job.job_id)
    path.write_text(json.dumps(asdict(job), indent=2), encoding="utf-8")
    return job


def cancel_job(cfg: ScraplingConfig, job_id: str) -> Dict[str, Any]:
    try:
        job = load_job(cfg, job_id)
    except JobRegistryError as exc:
        return {"job_id": job_id, "cancelled": False, **exc.as_dict()}

    if job is None:
        return {"job_id": job_id, "cancelled": False, "reason": "job_not_found"}

    if job.pid is None:
        job.error = "no_pid_recorded"
        update_job(cfg, job, status="cancel_failed")
        return {"job_id": job_id, "cancelled": False, "reason": "no_pid"}

    try:
        # First send SIGTERM; callers can decide if SIGKILL retries are needed.
        os.kill(job.pid, signal.SIGTERM)
        update_job(cfg, job, status="cancelling")
        result = {"job_id": job_id, "cancelled": True, "status": "cancelling"}
    except ProcessLookupError:
        job.error = "process_not_found"
        update_job(cfg, job, status="cancelled")
        result = {"job_id": job_id, "cancelled": False, "reason": "process_not_found"}
    except PermissionError as exc:
        job.error = f"permission_denied: {exc}"
        update_job(cfg, job, status="cancel_failed")
        result = {"job_id": job_id, "cancelled": False, "reason": "permission_denied", "error": str(exc)}
    except OSError as exc:
        job.error = f"os_error: {exc}"
        update_job(cfg, job, status="cancel_failed")
        result = {
            "job_id": job_id,
            "cancelled": False,
            "reason": "signal_failed",
            "error": str(exc),
            "error_type": type(exc).__name__,
        }

    return result
