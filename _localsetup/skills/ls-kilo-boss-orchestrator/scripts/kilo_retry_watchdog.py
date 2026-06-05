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
import time
from dataclasses import dataclass
from pathlib import Path

from lib.boss_orchestrator.retry_watchdog import acquire_lock as _acquire_lock
from lib.boss_orchestrator.retry_watchdog import capture_tail as _capture_tail
from lib.boss_orchestrator.retry_watchdog import emit_hermes_message as _emit_hermes_message
from lib.boss_orchestrator.retry_watchdog import ensure_tmux_session as _ensure_tmux_session
from lib.boss_orchestrator.retry_watchdog import has_tmux_session as _has_tmux_session
from lib.boss_orchestrator.retry_watchdog import hash_text as _hash_text
from lib.boss_orchestrator.retry_watchdog import list_tmux_sessions as _list_tmux_sessions
from lib.boss_orchestrator.retry_watchdog import load_state as _load_state
from lib.boss_orchestrator.retry_watchdog import match_any as _match_any
from lib.boss_orchestrator.retry_watchdog import now_iso as _now_iso
from lib.boss_orchestrator.retry_watchdog import pane_current_command as _pane_current_command
from lib.boss_orchestrator.retry_watchdog import pane_pid as _pane_pid
from lib.boss_orchestrator.retry_watchdog import process_alive as _process_alive
from lib.boss_orchestrator.retry_watchdog import read_recent as _read_recent
from lib.boss_orchestrator.retry_watchdog import release_lock as _release_lock
from lib.boss_orchestrator.retry_watchdog import run as _run
from lib.boss_orchestrator.retry_watchdog import send_command as _send_command
from lib.boss_orchestrator.retry_watchdog import send_ctrl_c as _send_ctrl_c
from lib.boss_orchestrator.retry_watchdog import send_prompt as _send_prompt
from lib.boss_orchestrator.retry_watchdog import write_state as _write_state

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
            script_version=SCRIPT_VERSION,
            service_name=SERVICE_NAME,
            phase_label=PHASE_LABEL,
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
