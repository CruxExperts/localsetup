from __future__ import annotations

import shlex
import time
from pathlib import Path
from typing import Any

from .constants import WAIT_PREFIX
from .sanitize import _ops_session_sequence, _sanitize_session
from .state import (
    _attach_command,
    _is_managed,
    _json_load,
    _json_write,
    _live_active,
    _prompt_channel,
    _state_dir,
    _status_payload,
)
from .tmux import (
    _is_pane_idle,
    _is_pane_waiting_sudo,
    _run_tmux,
    _session_exists,
    _session_list,
    _start_tmux_wait,
    _targeted_tmux,
    _wait_proc,
)


def _write_bootstrap(session: str) -> Path:
    state = _state_dir(session)
    state.mkdir(parents=True, exist_ok=True)
    script = state / "bootstrap.sh"
    content = f"""# tmux_ops managed session bootstrap
export TMUX_OPS_MANAGED=1
export TMUX_OPS_SESSION={shlex.quote(session)}
export TMUX_OPS_STATE_DIR={shlex.quote(str(state))}
__tmux_ops_prompt() {{
  printf '{{"session":"%s","idle":true,"ts":%s}}\\n' "$TMUX_OPS_SESSION" "$(date +%s)" > "$TMUX_OPS_STATE_DIR/idle.json"
  if [ -f "$TMUX_OPS_STATE_DIR/last_run_id" ]; then
    __tmux_ops_last_run="$(cat "$TMUX_OPS_STATE_DIR/last_run_id" 2>/dev/null || true)"
    rm -f "$TMUX_OPS_STATE_DIR/last_run_id"
    if [ -n "$__tmux_ops_last_run" ]; then
      tmux wait-for -S "{WAIT_PREFIX}-${{TMUX_OPS_SESSION}}-${{__tmux_ops_last_run}}-idle" 2>/dev/null || true
    fi
  fi
  tmux wait-for -S "{_prompt_channel(session)}" 2>/dev/null || true
}}
PROMPT_COMMAND=__tmux_ops_prompt
PS1='__tmux_ops__{session} \\$ '
"""
    script.write_text(content, encoding="utf-8")
    script.chmod(0o700)
    return script


def _bootstrap_session(session: str, create: bool) -> tuple[bool, str | None]:
    state = _state_dir(session)
    state.mkdir(parents=True, exist_ok=True)
    if create:
        r = _run_tmux(["new-session", "-d", "-s", session, "bash", "--noprofile", "--norc", "-i"])
        if r.returncode != 0:
            return False, r.stderr or f"tmux new-session exited {r.returncode}"
    script = _write_bootstrap(session)
    wait = _start_tmux_wait(_prompt_channel(session))
    r = _targeted_tmux(session, ["send-keys", "-t", "{target}", f"source {shlex.quote(str(script))}", "Enter"])
    if r.returncode != 0:
        return False, r.stderr or f"tmux send-keys exited {r.returncode}"
    if not _wait_proc(wait, 5.0):
        return False, "managed prompt hook did not signal idle"
    _json_write(state / "managed.json", {
        "session": session,
        "state_dir": str(state),
        "managed": True,
        "created_at": time.time(),
    })
    return True, None


def _ensure_managed_session(session: str) -> tuple[bool, str | None]:
    if not _session_exists(session):
        return _bootstrap_session(session, create=True)
    if _is_managed(session):
        return True, None
    if not _is_pane_idle(session):
        return False, "session exists but is not managed or idle"
    return _bootstrap_session(session, create=False)


def cmd_pick() -> dict[str, Any]:
    existing, list_err = _session_list()
    if list_err is not None:
        return {"error": "tmux list-sessions failed", "detail": list_err, "source": "pick"}

    skipped: list[dict[str, str]] = []
    existing = existing or set()
    for name in _ops_session_sequence():
        if name not in existing:
            ok, err = _bootstrap_session(name, create=True)
            if not ok:
                return {"error": "tmux session creation failed", "detail": err or "", "session": name, "source": "pick"}
            return {
                "session": name,
                "reason": "created",
                "state_dir": str(_state_dir(name)),
                "attach_command": _attach_command(name),
            }

        active = _live_active(name)
        if active:
            skipped.append({"session": name, "reason": "active"})
            continue
        if not _is_managed(name):
            if _is_pane_idle(name):
                skipped.append({"session": name, "reason": "unmanaged"})
            else:
                skipped.append({"session": name, "reason": "busy"})
            continue
        if _is_pane_idle(name):
            return {
                "session": name,
                "reason": "idle",
                "state_dir": str(_state_dir(name)),
                "attach_command": _attach_command(name),
            }
        if _is_pane_waiting_sudo(name):
            return {
                "session": name,
                "reason": "waiting_sudo",
                "state_dir": str(_state_dir(name)),
                "attach_command": _attach_command(name),
            }
        skipped.append({"session": name, "reason": "busy"})

    return {
        "error": "no safe tmux ops session available",
        "detail": "all ops sessions are active, busy, or unmanaged",
        "skipped": skipped,
        "source": "pick",
    }


def _write_probe_script(session: str) -> Path:
    state = _state_dir(session)
    path = state / "probe.sh"
    status_path = state / "probe.status.json"
    content = f"""#!/usr/bin/env bash
set +e
status_path={shlex.quote(str(status_path))}
session={shlex.quote(session)}
attach={shlex.quote(_attach_command(session))}
if ! command -v sudo >/dev/null 2>&1; then
  sudo_state=failed
  detail="sudo unavailable"
else
  output="$(sudo -vn 2>&1)"
  rc=$?
  if [ "$rc" -eq 0 ]; then
    sudo_state=ready
    detail=""
  elif printf '%s' "$output" | grep -Eiq 'password.*required|a password is required|terminal is required|authentication required'; then
    sudo_state=password_required
    detail="$output"
  else
    sudo_state=failed
    detail="$output"
  fi
fi
TMUX_PROBE_STATUS="$status_path" TMUX_PROBE_SESSION="$session" TMUX_PROBE_SUDO="$sudo_state" TMUX_PROBE_DETAIL="$detail" TMUX_PROBE_ATTACH="$attach" python3 - <<'PY'
import json, os, time
path = os.environ["TMUX_PROBE_STATUS"]
payload = {{
    "session": os.environ["TMUX_PROBE_SESSION"],
    "sudo": os.environ["TMUX_PROBE_SUDO"],
    "detail": os.environ.get("TMUX_PROBE_DETAIL", ""),
    "attach_command": os.environ["TMUX_PROBE_ATTACH"],
    "ts": time.time(),
}}
with open(path, "w", encoding="utf-8") as f:
    json.dump(payload, f, sort_keys=True)
    f.write("\\n")
PY
tmux wait-for -S "{WAIT_PREFIX}-{session}-probe"
"""
    path.write_text(content, encoding="utf-8")
    path.chmod(0o700)
    return path


def cmd_probe(target: str) -> dict[str, Any]:
    san = _sanitize_session(target)
    if san is None:
        return {"error": "invalid session name", "session": target, "source": "probe"}
    ok, err = _ensure_managed_session(san)
    if not ok:
        return {"error": "session is not ready for probe", "detail": err or "", "session": san, "source": "probe"}
    active = _live_active(san)
    if active:
        return {
            "error": "run already active",
            "detail": "use status or cancel before probing sudo",
            **_status_payload(san, str(active.get("run_id", ""))),
            "source": "probe",
        }

    script = _write_probe_script(san)
    channel = f"{WAIT_PREFIX}-{san}-probe"
    wait = _start_tmux_wait(channel)
    r = _targeted_tmux(san, ["send-keys", "-t", "{target}", f"bash {shlex.quote(str(script))}", "Enter"])
    if r.returncode != 0:
        return {"error": "tmux send-keys failed", "detail": r.stderr, "session": san, "source": "probe"}
    if not _wait_proc(wait, 10.0):
        return {"error": "sudo probe timed out", "session": san, "source": "probe", "attach_command": _attach_command(san)}

    payload = _json_load(_state_dir(san) / "probe.status.json")
    if not payload:
        return {"error": "sudo probe status missing", "session": san, "source": "probe"}
    if payload.get("sudo") == "password_required":
        r2 = _targeted_tmux(san, ["send-keys", "-t", "{target}", "sudo -v", "Enter"])
        if r2.returncode != 0:
            return {"error": "tmux send-keys failed", "detail": r2.stderr, "session": san, "source": "probe"}
    if payload.get("sudo") == "failed":
        return {
            "session": san,
            "sudo": "failed",
            "detail": payload.get("detail", ""),
            "attach_command": _attach_command(san),
        }
    return {
        "session": san,
        "sudo": payload.get("sudo", "unknown"),
        "detail": payload.get("detail", ""),
        "attach_command": _attach_command(san),
    }
