from __future__ import annotations

import shlex
import os
import shutil
import time
from pathlib import Path
from typing import Any

from .constants import WAIT_PREFIX
from .sanitize import _ops_session_sequence, _sanitize_session
from .state import (
    _attach_command,
    _is_managed,
    _json_write,
    _live_active,
    _prompt_channel,
    _state_dir,
    _status_payload,
)
from .sudo_gate import probe_sudo_gate
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
__tmux_ops_idle_hook() {{
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
if [ -z "${{PS1:-}}" ]; then
  PS1='\\u@\\h:\\w\\$ '
fi
if declare -p PROMPT_COMMAND >/dev/null 2>&1 && declare -p PROMPT_COMMAND 2>/dev/null | grep -q '^declare \\-a'; then
  PROMPT_COMMAND+=(__tmux_ops_idle_hook)
elif [ -n "${{PROMPT_COMMAND:-}}" ]; then
  PROMPT_COMMAND="${{PROMPT_COMMAND%';'}}; __tmux_ops_idle_hook"
else
  PROMPT_COMMAND=__tmux_ops_idle_hook
fi
"""
    script.write_text(content, encoding="utf-8")
    script.chmod(0o700)
    return script


def _interactive_bash() -> str:
    shell_env = os.environ.get("SHELL", "")
    shell = shutil.which(Path(shell_env).name) if shell_env else None
    if shell and Path(shell).name in {"bash", "rbash"}:
        return shell
    return shutil.which("bash") or "/bin/bash"


def _apply_session_options(session: str) -> tuple[bool, str | None]:
    for args in (
        ["set-option", "-t", session, "mouse", "on"],
        ["set-option", "-t", session, "history-limit", "100000"],
    ):
        result = _run_tmux(args)
        if result.returncode != 0:
            return False, result.stderr or result.stdout or f"tmux {' '.join(args)} exited {result.returncode}"
    return True, None


def _bootstrap_session(session: str, create: bool) -> tuple[bool, str | None]:
    state = _state_dir(session)
    state.mkdir(parents=True, exist_ok=True)
    if create:
        r = _run_tmux(["new-session", "-d", "-s", session, _interactive_bash(), "-i"])
        if r.returncode != 0:
            return False, r.stderr or f"tmux new-session exited {r.returncode}"
    ok, err = _apply_session_options(session)
    if not ok:
        return False, err
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

    return probe_sudo_gate(san)
