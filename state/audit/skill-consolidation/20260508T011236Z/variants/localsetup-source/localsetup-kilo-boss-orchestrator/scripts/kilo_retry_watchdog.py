#!/usr/bin/env python3
"""Deterministic phase-1 retry/deadman watchdog for Kilo orchestration failures.

Design goals:
- Offline-safe and non-AI recovery logic.
- Multi-strategy recovery ladder for common edge cases.
- Single-instance guard to avoid concurrent watchdog races.
- Rich Hermes escalation payload with machine/session/path/log telemetry.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import socket
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

SCRIPT_VERSION = "1.1.1"
SERVICE_NAME = "kilo-boss-orchestrator"
PHASE_LABEL = "phase-1.1"
DEFAULT_PROMPT = "Please resume with the most recently completed operation."
DEFAULT_FAILURE_RE = r"(?i)(timed_out|failed|error|traceback|broken pipe|send disconnect|orchestrator.*stuck)"
DEFAULT_RECOVERY_RE = (
    r"(?i)(\[OK\]|completed|resumed|gate passed|finalized|status.*idle)"
)


@dataclass
class RetryConfig:
    session: str
    prompt: str
    retry_interval_seconds: int
    max_retries: int
    failure_regex: str
    recovery_regex: str
    tail_lines: int
    cooldown_seconds: int
    state_root: Path
    hermes_outbox: Path
    log_files: list[Path]
    restart_on_unhealthy: bool
    kilo_launch_command: str
    startup_grace_seconds: int
    health_probe_delay_seconds: int
    unresponsive_threshold_seconds: int
    lock_file: Path
    lock_stale_seconds: int


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _tail_lines(path: Path, lines: int) -> list[str]:
    if not path.exists() or not path.is_file():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    except Exception:
        return []


def _has_tmux_session(session: str) -> bool:
    return _run(["tmux", "has-session", "-t", session]).returncode == 0


def _ensure_tmux_session(session: str) -> tuple[bool, str]:
    if _has_tmux_session(session):
        return True, "session exists"
    proc = _run(["tmux", "new-session", "-d", "-s", session])
    if proc.returncode == 0:
        return True, "session created"
    return False, (proc.stderr or proc.stdout or "failed to create session").strip()


def _capture_tail(session: str, lines: int = 40) -> str:
    proc = _run(["tmux", "capture-pane", "-t", session, "-p", "-S", f"-{lines}"])
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _pane_current_command(session: str) -> str:
    proc = _run(
        ["tmux", "display-message", "-p", "-t", session, "#{pane_current_command}"]
    )
    return (proc.stdout or "").strip().lower() if proc.returncode == 0 else ""


def _pane_pid(session: str) -> int | None:
    proc = _run(["tmux", "display-message", "-p", "-t", session, "#{pane_pid}"])
    if proc.returncode != 0:
        return None
    raw = (proc.stdout or "").strip()
    return int(raw) if raw.isdigit() else None


def _process_alive(pid: int | None) -> bool:
    return bool(pid and Path(f"/proc/{pid}").exists())


def _send_keys(
    session: str, key_or_text: str, literal: bool = False
) -> tuple[bool, str]:
    cmd = ["tmux", "send-keys", "-t", session]
    if literal:
        cmd += ["-l", key_or_text]
    else:
        cmd += [key_or_text]
    proc = _run(cmd)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "tmux send-keys failed").strip()
    return True, "ok"


def _send_prompt(session: str, prompt: str) -> tuple[bool, str]:
    ok, msg = _send_keys(session, prompt, literal=True)
    if not ok:
        return False, msg
    ok, msg = _send_keys(session, "Enter")
    return (ok, msg)


def _send_ctrl_c(session: str) -> None:
    _send_keys(session, "C-c")


def _send_command(session: str, command: str) -> tuple[bool, str]:
    if not command.strip():
        return False, "empty launch command"
    ok, msg = _send_keys(session, command, literal=True)
    if not ok:
        return False, msg
    ok, msg = _send_keys(session, "Enter")
    return (ok, msg)


def _load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _read_recent(log_files: Iterable[Path], tail_lines: int) -> dict[str, list[str]]:
    return {str(p): _tail_lines(p, tail_lines) for p in log_files}


def _match_any(lines_by_file: dict[str, list[str]], pattern: str) -> bool:
    rx = re.compile(pattern)
    for lines in lines_by_file.values():
        for line in lines:
            if rx.search(line):
                return True
    return False


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()


def _list_tmux_sessions() -> list[str]:
    proc = _run(["tmux", "list-sessions", "-F", "#{session_name}"])
    if proc.returncode != 0:
        return []
    return [x.strip() for x in proc.stdout.splitlines() if x.strip()]


def _collect_log_meta(paths: list[Path]) -> list[dict]:
    out: list[dict] = []
    for p in paths:
        item = {"path": str(p), "exists": p.exists()}
        if p.exists() and p.is_file():
            st = p.stat()
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


def _host_telemetry() -> dict:
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


def _assess_health(cfg: RetryConfig, state: dict) -> dict:
    session_exists = _has_tmux_session(cfg.session)
    current_command = _pane_current_command(cfg.session) if session_exists else ""
    pane_pid = _pane_pid(cfg.session) if session_exists else None
    pane_pid_alive = _process_alive(pane_pid)
    pane_tail = _capture_tail(cfg.session, 40) if session_exists else ""

    # Heuristic active signal; keep broad enough for wrappers.
    kilo_active = any(token in current_command for token in ["kilo", "python", "node"])

    now_epoch = int(time.time())
    prev_hash = str(state.get("last_pane_tail_hash", ""))
    prev_change_epoch = int(state.get("last_tail_change_epoch", now_epoch))

    tail_hash = _hash_text(pane_tail) if pane_tail else ""
    if tail_hash and tail_hash != prev_hash:
        last_change_epoch = now_epoch
    else:
        last_change_epoch = prev_change_epoch

    stagnant_for = max(0, now_epoch - last_change_epoch)
    unresponsive = session_exists and stagnant_for >= cfg.unresponsive_threshold_seconds

    return {
        "session_exists": session_exists,
        "pane_current_command": current_command,
        "pane_pid": pane_pid,
        "pane_pid_alive": pane_pid_alive,
        "kilo_active_heuristic": kilo_active,
        "pane_tail": pane_tail,
        "pane_tail_hash": tail_hash,
        "last_tail_change_epoch": last_change_epoch,
        "stagnant_for_seconds": stagnant_for,
        "unresponsive": unresponsive,
        "tmux_sessions": _list_tmux_sessions(),
    }


def _healthy_enough(health: dict) -> bool:
    return bool(
        health.get("session_exists")
        and health.get("kilo_active_heuristic")
        and not health.get("unresponsive")
    )


def _restart_in_session(cfg: RetryConfig, reason: str) -> tuple[bool, str]:
    ok, detail = _ensure_tmux_session(cfg.session)
    if not ok:
        return False, f"session ensure failed: {detail}"
    _send_ctrl_c(cfg.session)
    time.sleep(1)
    sent, msg = _send_command(cfg.session, cfg.kilo_launch_command)
    if not sent:
        return False, f"launch failed: {msg}"
    time.sleep(cfg.startup_grace_seconds)
    nudged, nmsg = _send_prompt(cfg.session, cfg.prompt)
    if not nudged:
        return False, f"resume nudge failed: {nmsg}"
    return True, f"restart in-session completed ({reason})"


def _recreate_session_and_launch(cfg: RetryConfig, reason: str) -> tuple[bool, str]:
    if _has_tmux_session(cfg.session):
        _run(["tmux", "kill-session", "-t", cfg.session])
        time.sleep(1)
    ok, detail = _ensure_tmux_session(cfg.session)
    if not ok:
        return False, f"session recreate failed: {detail}"
    sent, msg = _send_command(cfg.session, cfg.kilo_launch_command)
    if not sent:
        return False, f"launch failed: {msg}"
    time.sleep(cfg.startup_grace_seconds)
    nudged, nmsg = _send_prompt(cfg.session, cfg.prompt)
    if not nudged:
        return False, f"resume nudge failed: {nmsg}"
    return True, f"session recreated and Kilo launched ({reason})"


def _run_recovery_strategy(
    cfg: RetryConfig, strategy: str, reason: str
) -> tuple[bool, str]:
    if strategy == "prompt_nudge":
        return _send_prompt(cfg.session, cfg.prompt)
    if strategy == "interrupt_then_prompt":
        _send_ctrl_c(cfg.session)
        time.sleep(1)
        return _send_prompt(cfg.session, cfg.prompt)
    if strategy == "restart_in_session":
        return _restart_in_session(cfg, reason)
    if strategy == "recreate_session_and_launch":
        return _recreate_session_and_launch(cfg, reason)
    return False, f"unknown strategy: {strategy}"


def _choose_strategy(
    attempt: int, health: dict, restart_on_unhealthy: bool
) -> tuple[str, str]:
    if not health.get("session_exists", False):
        return (
            "recreate_session_and_launch" if restart_on_unhealthy else "prompt_nudge",
            "tmux session missing",
        )

    if health.get("unresponsive", False):
        if attempt <= 2:
            return ("interrupt_then_prompt", "pane appears frozen")
        return (
            "restart_in_session" if restart_on_unhealthy else "interrupt_then_prompt",
            "pane remains unresponsive",
        )

    if not health.get("kilo_active_heuristic", False):
        return (
            "restart_in_session" if restart_on_unhealthy else "prompt_nudge",
            "kilo process not active",
        )

    # Healthy-ish but error persisted: gentle-first then harder.
    if attempt == 1:
        return ("prompt_nudge", "transient failure suspected")
    if attempt == 2:
        return ("interrupt_then_prompt", "second recovery attempt")
    if attempt == 3:
        return (
            "restart_in_session" if restart_on_unhealthy else "interrupt_then_prompt",
            "third recovery attempt",
        )
    return (
        "recreate_session_and_launch"
        if restart_on_unhealthy
        else "interrupt_then_prompt",
        "last recovery attempt",
    )


def _emit_hermes_message(
    cfg: RetryConfig,
    reason: str,
    debug_bundle: dict[str, list[str]],
    attempts: int,
    strategies_used: list[dict],
    health: dict,
) -> Path:
    cfg.hermes_outbox.mkdir(parents=True, exist_ok=True)
    msg = {
        "schema_version": "1",
        "event_type": "kilo_deadman_retry_exhausted",
        "timestamp_utc": _now_iso(),
        "source": "kilo_retry_watchdog",
        "script_version": SCRIPT_VERSION,
        "service": SERVICE_NAME,
        "phase": PHASE_LABEL,
        "host": _host_telemetry(),
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
        "log_file_metadata": _collect_log_meta(cfg.log_files),
        "attempts": attempts,
        "strategies_used": strategies_used,
        "log_tail": debug_bundle,
        "next_action": "Hermes should notify operator and trigger higher-tier recovery workflow.",
    }
    out = cfg.hermes_outbox / f"kilo-deadman-exhausted-{int(time.time())}.json"
    out.write_text(json.dumps(msg, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def _acquire_lock(lock_file: Path, stale_seconds: int) -> tuple[bool, str, int | None]:
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
        os.write(fd, json.dumps({"pid": os.getpid(), "ts": _now_iso()}).encode("utf-8"))
        os.fsync(fd)
        return True, "lock acquired", fd
    except FileExistsError:
        return False, "lock exists", None
    except Exception as exc:
        return False, f"lock create failed: {exc}", None


def _release_lock(lock_file: Path, fd: int | None) -> None:
    try:
        if fd is not None:
            os.close(fd)
    except Exception:
        pass
    try:
        lock_file.unlink(missing_ok=True)
    except Exception:
        pass


def _build_config(args: argparse.Namespace) -> RetryConfig:
    state_root = Path(args.state_root).expanduser()
    log_files = [Path(p).expanduser() for p in args.log_file]
    if not log_files:
        log_files = [state_root / "events.log", state_root / "deadletter.jsonl"]

    lock_file = (
        Path(args.lock_file).expanduser()
        if args.lock_file
        else state_root / "retry_watchdog.lock"
    )

    return RetryConfig(
        session=args.session,
        prompt=args.prompt,
        retry_interval_seconds=max(1, int(args.retry_interval_seconds)),
        max_retries=max(1, int(args.max_retries)),
        failure_regex=args.failure_regex,
        recovery_regex=args.recovery_regex,
        tail_lines=max(10, int(args.tail_lines)),
        cooldown_seconds=max(0, int(args.cooldown_seconds)),
        state_root=state_root,
        hermes_outbox=Path(args.hermes_outbox).expanduser(),
        log_files=log_files,
        restart_on_unhealthy=bool(args.restart_on_unhealthy),
        kilo_launch_command=args.kilo_launch_command.strip(),
        startup_grace_seconds=max(1, int(args.startup_grace_seconds)),
        health_probe_delay_seconds=max(1, int(args.health_probe_delay_seconds)),
        unresponsive_threshold_seconds=max(5, int(args.unresponsive_threshold_seconds)),
        lock_file=lock_file,
        lock_stale_seconds=max(30, int(args.lock_stale_seconds)),
    )


def run_once(cfg: RetryConfig) -> int:
    lock_ok, lock_msg, lock_fd = _acquire_lock(cfg.lock_file, cfg.lock_stale_seconds)
    if not lock_ok:
        print(f"[OK] watchdog skipped: {lock_msg}")
        return 0

    try:
        state_file = cfg.state_root / "retry_watchdog_state.json"
        state = _load_state(state_file)

        recent = _read_recent(cfg.log_files, cfg.tail_lines)
        failure_detected = _match_any(recent, cfg.failure_regex)
        health = _assess_health(cfg, state)

        if not failure_detected:
            _write_state(
                state_file,
                {
                    "updated_at": _now_iso(),
                    "phase": PHASE_LABEL,
                    "status": "idle",
                    "reason": "no failure marker detected",
                    "log_files": [str(p) for p in cfg.log_files],
                    "last_pane_tail_hash": health.get("pane_tail_hash", ""),
                    "last_tail_change_epoch": health.get(
                        "last_tail_change_epoch", int(time.time())
                    ),
                    "health": health,
                },
            )
            print("[OK] no failure marker detected")
            return 0

        now_epoch = int(time.time())
        last_trigger = int(state.get("last_trigger_epoch", 0))
        if cfg.cooldown_seconds > 0 and now_epoch - last_trigger < cfg.cooldown_seconds:
            print("[OK] cooldown active; skipping retry burst")
            return 0

        attempts = 0
        recovered = False
        strategies_used: list[dict] = []

        for idx in range(1, cfg.max_retries + 1):
            attempts = idx

            health = _assess_health(cfg, state)
            strategy, reason = _choose_strategy(idx, health, cfg.restart_on_unhealthy)
            ok, detail = _run_recovery_strategy(cfg, strategy, reason)
            strategies_used.append(
                {
                    "attempt": idx,
                    "strategy": strategy,
                    "reason": reason,
                    "result": "ok" if ok else "failed",
                    "detail": detail,
                    "ts": _now_iso(),
                }
            )
            print(
                f"[INFO] retry {idx}/{cfg.max_retries}: strategy={strategy} result={detail}"
            )

            time.sleep(cfg.retry_interval_seconds)

            post = _read_recent(cfg.log_files, cfg.tail_lines)
            recovered_signal = _match_any(post, cfg.recovery_regex)
            health_post = _assess_health(cfg, state)

            # Recovery pass condition is deterministic and non-AI:
            #   (a) explicit recovery marker OR
            #   (b) healthy service envelope restored.
            if recovered_signal or _healthy_enough(health_post):
                recovered = True
                health = health_post
                break

        health = _assess_health(cfg, state)

        if recovered:
            _write_state(
                state_file,
                {
                    "updated_at": _now_iso(),
                    "phase": PHASE_LABEL,
                    "status": "recovered",
                    "attempts": attempts,
                    "last_trigger_epoch": now_epoch,
                    "log_files": [str(p) for p in cfg.log_files],
                    "strategies_used": strategies_used,
                    "last_pane_tail_hash": health.get("pane_tail_hash", ""),
                    "last_tail_change_epoch": health.get(
                        "last_tail_change_epoch", int(time.time())
                    ),
                    "health": health,
                },
            )
            print(f"[OK] recovered after {attempts} retries")
            return 0

        bundle = _read_recent(cfg.log_files, cfg.tail_lines)
        out = _emit_hermes_message(
            cfg,
            reason="retry budget exhausted without recovery",
            debug_bundle=bundle,
            attempts=attempts,
            strategies_used=strategies_used,
            health=health,
        )
        _write_state(
            state_file,
            {
                "updated_at": _now_iso(),
                "phase": PHASE_LABEL,
                "status": "failed",
                "attempts": attempts,
                "last_trigger_epoch": now_epoch,
                "hermes_message": str(out),
                "log_files": [str(p) for p in cfg.log_files],
                "strategies_used": strategies_used,
                "last_pane_tail_hash": health.get("pane_tail_hash", ""),
                "last_tail_change_epoch": health.get(
                    "last_tail_change_epoch", int(time.time())
                ),
                "health": health,
            },
        )
        print(f"[ERROR] retries exhausted; Hermes payload emitted: {out}")
        return 3
    finally:
        _release_lock(cfg.lock_file, lock_fd)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Deterministic Kilo retry/deadman watchdog")
    p.add_argument(
        "--session", default="ops", help="tmux session target (default: ops)"
    )
    p.add_argument("--prompt", default=DEFAULT_PROMPT, help="resume prompt text")
    p.add_argument("--retry-interval-seconds", type=int, default=15)
    p.add_argument("--max-retries", type=int, default=4)
    p.add_argument("--failure-regex", default=DEFAULT_FAILURE_RE)
    p.add_argument("--recovery-regex", default=DEFAULT_RECOVERY_RE)
    p.add_argument("--tail-lines", type=int, default=50)
    p.add_argument("--cooldown-seconds", type=int, default=120)
    p.add_argument(
        "--state-root",
        default=".kilo/state/orchestrator",
        help="orchestrator state root (default: .kilo/state/orchestrator)",
    )
    p.add_argument(
        "--hermes-outbox",
        default=".kilo/state/hermes/outbox",
        help="Hermes JSON outbox directory",
    )
    p.add_argument(
        "--log-file",
        action="append",
        default=[],
        help="log file to scan (repeatable); defaults to events.log + deadletter.jsonl",
    )
    p.add_argument(
        "--restart-on-unhealthy",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="restart Kilo when session missing/unresponsive/inactive (default: true)",
    )
    p.add_argument(
        "--kilo-launch-command",
        default="kilo",
        help="command used to (re)launch Kilo in tmux session",
    )
    p.add_argument(
        "--startup-grace-seconds",
        type=int,
        default=6,
        help="seconds to wait after launch before resume nudge",
    )
    p.add_argument(
        "--health-probe-delay-seconds",
        type=int,
        default=3,
        help="delay before post-strategy health probe",
    )
    p.add_argument(
        "--unresponsive-threshold-seconds",
        type=int,
        default=45,
        help="pane stagnation threshold before classifying as unresponsive",
    )
    p.add_argument(
        "--lock-file",
        default="",
        help="single-instance lock file path (default: <state-root>/retry_watchdog.lock)",
    )
    p.add_argument(
        "--lock-stale-seconds",
        type=int,
        default=300,
        help="stale lock age before automatic reclaim",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()
    cfg = _build_config(args)
    return run_once(cfg)


if __name__ == "__main__":
    raise SystemExit(main())
