from __future__ import annotations

import shlex
import time
from pathlib import Path
from typing import Any

from .constants import WAIT_PREFIX
from .state import _attach_command, _json_load, _json_write, _state_dir
from .tmux import (
    _is_pane_waiting_sudo,
    _pane_target,
    _pane_tty,
    _start_tmux_wait,
    _targeted_tmux,
    _wait_proc,
)

DEFAULT_GATE_FRESHNESS_SECONDS = 60.0


def _sudo_gate_path(session: str) -> Path:
    return _state_dir(session) / "sudo_gate.json"


def _probe_status_path(session: str) -> Path:
    return _state_dir(session) / "probe.status.json"


def _pane_identity(session: str) -> tuple[dict[str, str | None], str | None]:
    pane_id, pane_err = _pane_target(session)
    if pane_id is None:
        return {"pane_id": None, "pane_tty": None}, pane_err
    pane_tty, tty_err = _pane_tty(session)
    if pane_tty is None:
        return {"pane_id": pane_id, "pane_tty": None}, tty_err
    return {"pane_id": pane_id, "pane_tty": pane_tty}, None


def _action_payload(
    session: str,
    *,
    sudo: str,
    detail: str = "",
    checked_at: float | None = None,
    probe_command: str = "sudo -Nnv",
    pane_id: str | None = None,
    pane_tty: str | None = None,
) -> dict[str, Any]:
    checked = checked_at or time.time()
    return {
        "session": session,
        "sudo": sudo,
        "gate_state": sudo,
        "action_required": sudo != "ready",
        "user_command": "sudo -v" if sudo == "password_required" else None,
        "attach_command": _attach_command(session),
        "next_probe_command": f"tmux_ops probe -t {session}",
        "pane_id": pane_id,
        "pane_tty": pane_tty,
        "checked_at": checked,
        "ts": checked,
        "probe_command": probe_command,
        "detail": detail,
    }


def _write_gate_payload(session: str, payload: dict[str, Any]) -> dict[str, Any]:
    _json_write(_sudo_gate_path(session), payload)
    _json_write(_probe_status_path(session), payload)
    return payload


def _write_probe_script(session: str) -> Path:
    state = _state_dir(session)
    state.mkdir(parents=True, exist_ok=True)
    path = state / "probe.sh"
    gate_path = _sudo_gate_path(session)
    alias_path = _probe_status_path(session)
    identity, _ = _pane_identity(session)
    content = f"""#!/usr/bin/env bash
set +e
gate_path={shlex.quote(str(gate_path))}
alias_path={shlex.quote(str(alias_path))}
session={shlex.quote(session)}
attach={shlex.quote(_attach_command(session))}
pane_id={shlex.quote(str(identity.get("pane_id") or ""))}
pane_tty={shlex.quote(str(identity.get("pane_tty") or ""))}
if ! command -v sudo >/dev/null 2>&1; then
  sudo_state=failed
  detail="sudo unavailable"
  probe_command="sudo -Nnv"
else
  output="$(sudo -Nnv 2>&1)"
  rc=$?
  probe_command="sudo -Nnv"
  if [ "$rc" -ne 0 ] && printf '%s' "$output" | grep -Eiq -- 'invalid option|illegal option|unknown option|usage: sudo'; then
    output="$(sudo -vn 2>&1)"
    rc=$?
    probe_command="sudo -vn"
  fi
  if [ "$rc" -eq 0 ]; then
    sudo_state=ready
    detail=""
  elif printf '%s' "$output" | grep -Eiq 'password.*required|a password is required|terminal is required|authentication required|a terminal is required'; then
    sudo_state=password_required
    detail="$output"
  else
    sudo_state=failed
    detail="$output"
  fi
fi
TMUX_PROBE_GATE="$gate_path" TMUX_PROBE_ALIAS="$alias_path" TMUX_PROBE_SESSION="$session" \\
TMUX_PROBE_SUDO="$sudo_state" TMUX_PROBE_DETAIL="$detail" TMUX_PROBE_ATTACH="$attach" \\
TMUX_PROBE_COMMAND="$probe_command" TMUX_PROBE_PANE_ID="$pane_id" TMUX_PROBE_PANE_TTY="$pane_tty" \\
python3 - <<'PY'
import json, os, time
checked = time.time()
sudo = os.environ["TMUX_PROBE_SUDO"]
payload = {{
    "session": os.environ["TMUX_PROBE_SESSION"],
    "sudo": sudo,
    "gate_state": sudo,
    "action_required": sudo != "ready",
    "user_command": "sudo -v" if sudo == "password_required" else None,
    "attach_command": os.environ["TMUX_PROBE_ATTACH"],
    "next_probe_command": "tmux_ops probe -t " + os.environ["TMUX_PROBE_SESSION"],
    "pane_id": os.environ.get("TMUX_PROBE_PANE_ID") or None,
    "pane_tty": os.environ.get("TMUX_PROBE_PANE_TTY") or None,
    "checked_at": checked,
    "ts": checked,
    "probe_command": os.environ["TMUX_PROBE_COMMAND"],
    "detail": os.environ.get("TMUX_PROBE_DETAIL", ""),
}}
for path in (os.environ["TMUX_PROBE_GATE"], os.environ["TMUX_PROBE_ALIAS"]):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, sort_keys=True)
        f.write("\\n")
PY
tmux wait-for -S "{WAIT_PREFIX}-{session}-probe"
"""
    path.write_text(content, encoding="utf-8")
    path.chmod(0o700)
    return path


def probe_sudo_gate(session: str) -> dict[str, Any]:
    identity, err = _pane_identity(session)
    if err:
        return _action_payload(
            session,
            sudo="failed",
            detail=err,
            pane_id=identity.get("pane_id"),
            pane_tty=identity.get("pane_tty"),
        )
    script = _write_probe_script(session)
    channel = f"{WAIT_PREFIX}-{session}-probe"
    wait = _start_tmux_wait(channel)
    r = _targeted_tmux(session, ["send-keys", "-t", "{target}", f"bash {shlex.quote(str(script))}", "Enter"])
    if r.returncode != 0:
        payload = _action_payload(
            session,
            sudo="failed",
            detail=r.stderr,
            pane_id=identity.get("pane_id"),
            pane_tty=identity.get("pane_tty"),
        )
        return _write_gate_payload(session, payload)
    if not _wait_proc(wait, 10.0):
        payload = _action_payload(
            session,
            sudo="failed",
            detail="sudo probe timed out",
            pane_id=identity.get("pane_id"),
            pane_tty=identity.get("pane_tty"),
        )
        return _write_gate_payload(session, payload)
    payload = _json_load(_sudo_gate_path(session)) or _json_load(_probe_status_path(session))
    if not payload:
        payload = _action_payload(
            session,
            sudo="failed",
            detail="sudo probe status missing",
            pane_id=identity.get("pane_id"),
            pane_tty=identity.get("pane_tty"),
        )
        return _write_gate_payload(session, payload)
    return payload


def current_sudo_gate(session: str) -> dict[str, Any] | None:
    return _json_load(_sudo_gate_path(session)) or _json_load(_probe_status_path(session))


def gate_is_fresh_ready(session: str, *, freshness: float = DEFAULT_GATE_FRESHNESS_SECONDS) -> bool:
    gate = current_sudo_gate(session)
    if not gate or gate.get("sudo") != "ready" or gate.get("gate_state") != "ready":
        return False
    checked_at = gate.get("checked_at", gate.get("ts"))
    if not isinstance(checked_at, (int, float)) or time.time() - float(checked_at) > freshness:
        return False
    identity, err = _pane_identity(session)
    if err:
        return False
    return gate.get("pane_id") == identity.get("pane_id") and gate.get("pane_tty") == identity.get("pane_tty")


def ensure_ready_gate(session: str, *, freshness: float = DEFAULT_GATE_FRESHNESS_SECONDS) -> dict[str, Any]:
    if _is_pane_waiting_sudo(session):
        identity, _ = _pane_identity(session)
        return _action_payload(
            session,
            sudo="password_required",
            detail="pane is waiting at a sudo/password prompt",
            pane_id=identity.get("pane_id"),
            pane_tty=identity.get("pane_tty"),
        )
    if gate_is_fresh_ready(session, freshness=freshness):
        return current_sudo_gate(session) or _action_payload(session, sudo="failed", detail="sudo gate missing")
    return probe_sudo_gate(session)


def sudo_blocked_payload(session: str) -> dict[str, Any] | None:
    if _is_pane_waiting_sudo(session):
        identity, _ = _pane_identity(session)
        return _action_payload(
            session,
            sudo="password_required",
            detail="pane is waiting at a sudo/password prompt",
            pane_id=identity.get("pane_id"),
            pane_tty=identity.get("pane_tty"),
        )
    gate = current_sudo_gate(session)
    if gate and gate.get("sudo") == "password_required":
        return gate
    return None
