from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from .constants import DEFAULT_TAIL_LINES, STATE_ROOT, WAIT_PREFIX

def _state_dir(session: str) -> Path:
    return STATE_ROOT / session


def _attach_command(session: str) -> str:
    return f"tmux new-session -A -s {session}"


def _run_channel(session: str, run_id: str) -> str:
    return f"{WAIT_PREFIX}-{session}-{run_id}-idle"


def _prompt_channel(session: str) -> str:
    return f"{WAIT_PREFIX}-{session}-idle"


def _pane_operation_lock_path(session: str) -> Path:
    return _state_dir(session) / "pane-operation.lock"


def _acquire_pane_operation_lock(session: str) -> int | None:
    path = _pane_operation_lock_path(session)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        return os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return None


def _release_pane_operation_lock(session: str, fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        _pane_operation_lock_path(session).unlink()
    except OSError:
        pass


def _status_path(session: str, run_id: str) -> Path:
    return _state_dir(session) / f"{run_id}.status.json"


def _json_load(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _json_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _tail(path: Path, lines: int) -> str:
    if lines <= 0 or not path.exists():
        return ""
    try:
        data = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(data[-lines:])


def _active_path(session: str) -> Path:
    return _state_dir(session) / "active.json"


def _live_active(session: str) -> dict[str, Any] | None:
    active = _json_load(_active_path(session))
    if not active:
        return None
    run_id = active.get("run_id")
    if isinstance(run_id, str):
        status = _json_load(_status_path(session, run_id))
        if status and status.get("status") in {"completed", "cancelled", "failed"}:
            try:
                _active_path(session).unlink()
            except OSError:
                pass
            return None
    return active


def _is_managed(session: str) -> bool:
    return (_state_dir(session) / "managed.json").exists()
def _status_payload(session: str, run_id: str, tail_lines: int = DEFAULT_TAIL_LINES) -> dict[str, Any]:
    status = _json_load(_status_path(session, run_id)) or {}
    status.setdefault("session", session)
    status.setdefault("run_id", run_id)
    status.setdefault("status", "unknown")
    status.setdefault("attach_command", _attach_command(session))
    if status.get("status") == "running" and isinstance(status.get("started_at"), (int, float)):
        status["elapsed_s"] = round(time.time() - float(status["started_at"]), 3)
    log_path = status.get("log_path")
    if isinstance(log_path, str):
        status["tail"] = _tail(Path(log_path), tail_lines)
    else:
        status["tail"] = ""
    return status
