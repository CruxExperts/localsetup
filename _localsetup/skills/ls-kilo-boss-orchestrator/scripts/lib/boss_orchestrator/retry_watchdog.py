"""Support helpers for the Kilo retry watchdog."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def tail_lines(path: Path, lines: int) -> list[str]:
    if not path.exists() or not path.is_file():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    except Exception:
        return []


def has_tmux_session(session: str) -> bool:
    return run(["tmux", "has-session", "-t", session]).returncode == 0


def ensure_tmux_session(session: str) -> tuple[bool, str]:
    if has_tmux_session(session):
        return True, "session exists"
    proc = run(["tmux", "new-session", "-d", "-s", session])
    if proc.returncode == 0:
        return True, "session created"
    return False, (proc.stderr or proc.stdout or "failed to create session").strip()


def capture_tail(session: str, lines: int = 40) -> str:
    proc = run(["tmux", "capture-pane", "-t", session, "-p", "-S", f"-{lines}"])
    return proc.stdout.strip() if proc.returncode == 0 else ""


def pane_current_command(session: str) -> str:
    proc = run(
        ["tmux", "display-message", "-p", "-t", session, "#{pane_current_command}"]
    )
    return (proc.stdout or "").strip().lower() if proc.returncode == 0 else ""


def pane_pid(session: str) -> int | None:
    proc = run(["tmux", "display-message", "-p", "-t", session, "#{pane_pid}"])
    if proc.returncode != 0:
        return None
    raw = (proc.stdout or "").strip()
    return int(raw) if raw.isdigit() else None


def process_alive(pid: int | None) -> bool:
    return bool(pid and Path(f"/proc/{pid}").exists())


def send_keys(session: str, key_or_text: str, literal: bool = False) -> tuple[bool, str]:
    cmd = ["tmux", "send-keys", "-t", session]
    if literal:
        cmd += ["-l", key_or_text]
    else:
        cmd += [key_or_text]
    proc = run(cmd)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "tmux send-keys failed").strip()
    return True, "ok"


def send_prompt(session: str, prompt: str) -> tuple[bool, str]:
    ok, msg = send_keys(session, prompt, literal=True)
    if not ok:
        return False, msg
    ok, msg = send_keys(session, "Enter")
    return ok, msg


def send_ctrl_c(session: str) -> None:
    send_keys(session, "C-c")


def send_command(session: str, command: str) -> tuple[bool, str]:
    if not command.strip():
        return False, "empty launch command"
    ok, msg = send_keys(session, command, literal=True)
    if not ok:
        return False, msg
    ok, msg = send_keys(session, "Enter")
    return ok, msg


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def read_recent(log_files: Iterable[Path], tail_count: int) -> dict[str, list[str]]:
    return {str(p): tail_lines(p, tail_count) for p in log_files}


def match_any(lines_by_file: dict[str, list[str]], pattern: str) -> bool:
    rx = re.compile(pattern)
    for lines in lines_by_file.values():
        for line in lines:
            if rx.search(line):
                return True
    return False


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()


def list_tmux_sessions() -> list[str]:
    proc = run(["tmux", "list-sessions", "-F", "#{session_name}"])
    if proc.returncode != 0:
        return []
    return [x.strip() for x in proc.stdout.splitlines() if x.strip()]


def collect_log_meta(paths: list[Path]) -> list[dict]:
    out: list[dict] = []
    for path in paths:
        item = {"path": str(path), "exists": path.exists()}
        if path.exists() and path.is_file():
            st = path.stat()
            item.update(
                {
                    "size_bytes": st.st_size,
                    "mtime_epoch": int(st.st_mtime),
                    "mtime_utc": datetime.fromtimestamp(
                        st.st_mtime, timezone.utc
                    ).isoformat(),
                }
            )
        out.append(item)
    return out


def host_telemetry() -> dict:
    host = socket.gethostname()
    fqdn = socket.getfqdn()
    ip = ""
    try:
        ip = socket.gethostbyname(host)
    except Exception:
        ip = ""
    return {
        "hostname": host,
        "fqdn": fqdn,
        "primary_ipv4": ip,
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "python_version": platform.python_version(),
        "pid": os.getpid(),
        "cwd": str(Path.cwd()),
    }


def emit_hermes_message(
    cfg,
    *,
    reason: str,
    debug_bundle: dict[str, list[str]],
    attempts: int,
    strategies_used: list[dict],
    health: dict,
    script_version: str,
    service_name: str,
    phase_label: str,
) -> Path:
    cfg.hermes_outbox.mkdir(parents=True, exist_ok=True)
    msg = {
        "schema_version": "1",
        "event_type": "kilo_deadman_retry_exhausted",
        "timestamp_utc": now_iso(),
        "source": "kilo_retry_watchdog",
        "script_version": script_version,
        "service": service_name,
        "phase": phase_label,
        "host": host_telemetry(),
        "reason": reason,
        "tmux": {
            "session": cfg.session,
            "kilo_launch_command": cfg.kilo_launch_command,
            "health": health,
        },
        "recovery_policy": {
            "restart_on_unhealthy": cfg.restart_on_unhealthy,
            "retry_interval_seconds": cfg.retry_interval_seconds,
            "max_retries": cfg.max_retries,
            "cooldown_seconds": cfg.cooldown_seconds,
            "startup_grace_seconds": cfg.startup_grace_seconds,
            "health_probe_delay_seconds": cfg.health_probe_delay_seconds,
            "unresponsive_threshold_seconds": cfg.unresponsive_threshold_seconds,
            "resume_prompt": cfg.prompt,
            "failure_regex": cfg.failure_regex,
            "recovery_regex": cfg.recovery_regex,
        },
        "paths": {
            "state_root": str(cfg.state_root),
            "state_file": str(cfg.state_root / "retry_watchdog_state.json"),
            "lock_file": str(cfg.lock_file),
            "hermes_outbox": str(cfg.hermes_outbox),
            "log_files": [str(p) for p in cfg.log_files],
        },
        "log_file_metadata": collect_log_meta(cfg.log_files),
        "attempts": attempts,
        "strategies_used": strategies_used,
        "log_tail": debug_bundle,
        "next_action": "Hermes should notify operator and trigger higher-tier recovery workflow.",
    }
    out = cfg.hermes_outbox / f"kilo-deadman-exhausted-{int(time.time())}.json"
    out.write_text(json.dumps(msg, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def acquire_lock(lock_file: Path, stale_seconds: int) -> tuple[bool, str, int | None]:
    lock_file.parent.mkdir(parents=True, exist_ok=True)

    if lock_file.exists():
        try:
            age = int(time.time() - lock_file.stat().st_mtime)
            if age >= stale_seconds:
                lock_file.unlink(missing_ok=True)
            else:
                return False, f"lock active ({age}s old)", None
        except Exception as exc:
            return False, f"lock check failed: {exc}", None

    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(lock_file), flags, 0o644)
        os.write(fd, json.dumps({"pid": os.getpid(), "ts": now_iso()}).encode("utf-8"))
        os.fsync(fd)
        return True, "lock acquired", fd
    except FileExistsError:
        return False, "lock exists", None
    except Exception as exc:
        return False, f"lock create failed: {exc}", None


def release_lock(lock_file: Path, fd: int | None) -> None:
    try:
        if fd is not None:
            os.close(fd)
    except Exception:
        pass
    try:
        lock_file.unlink(missing_ok=True)
    except Exception:
        pass
