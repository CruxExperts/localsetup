#!/usr/bin/env python3
# Purpose: Managed tmux ops workflow: pick/probe/run/status/cancel plus legacy send/wait.
# Created: 2026-02-25
# Last updated: 2026-05-08

"""
Tmux ops workflow tool.

Primary path:
  pick -> probe -> run

Managed sessions are bootstrapped with a prompt hook that signals tmux wait-for
when the shell is actually idle. Commands run from generated scripts whose
stdout/stderr is tee'd to per-run logs. Timeouts report "running" and keep the
active run intact; cancellation is explicit via cancel --run-id.

Legacy send/wait remain for compatibility and diagnostics.
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
import uuid
from collections import namedtuple
from pathlib import Path
from typing import Any

DEFAULT_SEND_DELAY = 0.5
MAX_CMD_LEN = 32768

FAST_POLL_INTERVAL = 0.05
FAST_PHASE_DURATION = 2.0
MED_POLL_INTERVAL = 0.3
MED_PHASE_DURATION = 15.0
SLOW_POLL_INTERVAL = 1.0
DEFAULT_WAIT_TIMEOUT = 30.0
DEFAULT_RUN_TIMEOUT = 3600.0
DEFAULT_TAIL_LINES = 120

DEFAULT_IDLE_RE_STR = r"^.*[$#]\s*$"
IDLE_PROMPT_RE = re.compile(os.environ.get("TMUX_OPS_IDLE_RE", DEFAULT_IDLE_RE_STR))
PASSWORD_PROMPT_RE = re.compile(r"\[sudo\]\s*password\s+for|password.*:", re.I)

TmuxResult = namedtuple("TmuxResult", ("returncode", "stdout", "stderr"))

OPS_BASE = "ops"
SESSION_PATTERN = re.compile(r"^ops(\d*)$")
MAX_SESSION_NUM = 20

STATE_ROOT = Path(os.environ.get("TMUX_OPS_STATE_ROOT", "/tmp/localsetup-tmux-ops"))
WAIT_PREFIX = "localsetup-tmux-ops"

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _strip_control(s: str) -> str:
    if not s:
        return s
    return _CONTROL_CHARS.sub("", s)


def _tmux_cmd(args: list[str]) -> list[str]:
    base = shlex.split(os.environ.get("TMUX_OPS_TMUX", "tmux"))
    return base + args


def _run_tmux(args: list[str], timeout: float = 5.0) -> TmuxResult:
    try:
        r = subprocess.run(
            _tmux_cmd(args),
            capture_output=True,
            text=True,
            timeout=timeout,
            errors="replace",
        )
        return TmuxResult(r.returncode, r.stdout or "", r.stderr or "")
    except subprocess.TimeoutExpired as e:
        return TmuxResult(-1, "", f"tmux timeout after {e.timeout}s: {e.cmd}")
    except OSError as e:
        return TmuxResult(-1, "", f"tmux execution failed: {type(e).__name__}: {e}")


def _start_tmux_wait(channel: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        _tmux_cmd(["wait-for", channel]),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _wait_proc(proc: subprocess.Popen[str], timeout: float) -> bool:
    try:
        proc.wait(timeout=timeout)
        return proc.returncode == 0
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.communicate(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        return False


def _session_list() -> tuple[set[str] | None, str | None]:
    result = _run_tmux(["list-sessions", "-F", "#{session_name}"])
    if result.returncode != 0:
        detail = result.stderr or result.stdout or f"tmux list-sessions exited {result.returncode}"
        detail_lower = detail.lower()
        if "no server running" in detail_lower or "error connecting to" in detail_lower:
            return set(), None
        return None, detail
    return {s.strip() for s in result.stdout.splitlines() if s.strip()}, None


def _session_exists(session: str) -> bool:
    r = _run_tmux(["has-session", "-t", session])
    return r.returncode == 0


def _pane_target(session: str) -> tuple[str | None, str | None]:
    result = _run_tmux(["list-panes", "-t", session, "-F", "#{pane_id}"])
    if result.returncode != 0:
        return None, result.stderr or f"tmux list-panes exited {result.returncode}"
    panes = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not panes:
        return None, f"no panes found for session {session}"
    return panes[0], None


def _targeted_tmux(session: str, args: list[str], timeout: float = 5.0) -> TmuxResult:
    pane, err = _pane_target(session)
    if pane is None:
        return TmuxResult(-1, "", err or f"unable to resolve pane target for {session}")
    resolved_args = [pane if arg == "{target}" else arg for arg in args]
    result = _run_tmux(resolved_args, timeout=timeout)
    if result.returncode != 0:
        detail = result.stderr or result.stdout
        if detail:
            detail = f"{detail.rstrip()}\nresolved_target={pane}"
        else:
            detail = f"resolved_target={pane}"
        return TmuxResult(result.returncode, result.stdout, detail)
    return result


def _cursor_y(target: str) -> tuple[int | None, str | None]:
    result = _targeted_tmux(target, ["display-message", "-t", "{target}", "-p", "-F", "#{cursor_y}"])
    if result.returncode != 0:
        return None, result.stderr or f"tmux display-message exited {result.returncode}"
    try:
        return int(result.stdout.strip()), None
    except ValueError:
        return None, f"invalid cursor_y output: {result.stdout!r}"


def _capture_line(target: str, line_index: int) -> tuple[str, str | None]:
    result = _targeted_tmux(target, [
        "capture-pane", "-t", "{target}", "-p", "-S", str(line_index), "-E", str(line_index),
    ])
    if result.returncode != 0:
        return "", result.stderr or f"tmux capture-pane exited {result.returncode}"
    return result.stdout.strip(), None


def _is_pane_idle(target: str, idle_re: re.Pattern[str] | None = None) -> bool:
    pattern = idle_re or IDLE_PROMPT_RE
    cy, _ = _cursor_y(target)
    if cy is None:
        return False
    line, _ = _capture_line(target, cy)
    return bool(pattern.match(line))


def _is_pane_waiting_sudo(target: str) -> bool:
    cy, _ = _cursor_y(target)
    if cy is None:
        return False
    line, _ = _capture_line(target, cy)
    return bool(PASSWORD_PROMPT_RE.search(line))


def _snapshot_cursor(target: str) -> int | None:
    cy, _ = _cursor_y(target)
    return cy


def _ops_session_sequence() -> list[str]:
    return [OPS_BASE] + [f"{OPS_BASE}{i}" for i in range(1, MAX_SESSION_NUM + 1)]


def _sanitize_session(name: str) -> str | None:
    if not name or not isinstance(name, str):
        return None
    s = _strip_control(name.strip())
    if len(s) > 32 or SESSION_PATTERN.fullmatch(s) is None:
        return None
    return s


def _sanitize_command(raw: str) -> tuple[str | None, str | None]:
    if not raw or not isinstance(raw, str):
        return None, "empty or non-string command"
    s = _strip_control(raw.strip())
    if not s:
        return None, "command empty after sanitization"
    if len(s) > MAX_CMD_LEN:
        return None, f"command exceeds max length {MAX_CMD_LEN} (got {len(s)})"
    return s, None


def _compile_idle_re(pattern_str: str | None) -> tuple[re.Pattern[str] | None, str | None]:
    if pattern_str is None:
        return None, None
    try:
        return re.compile(pattern_str), None
    except re.error as e:
        return None, f"invalid regex {pattern_str!r}: {e}"


def _state_dir(session: str) -> Path:
    return STATE_ROOT / session


def _attach_command(session: str) -> str:
    return f"tmux new-session -A -s {session}"


def _run_channel(session: str, run_id: str) -> str:
    return f"{WAIT_PREFIX}-{session}-{run_id}-idle"


def _prompt_channel(session: str) -> str:
    return f"{WAIT_PREFIX}-{session}-idle"


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


def _command_from_remainder(parts: list[str]) -> tuple[str | None, str | None]:
    if parts and parts[0] == "--":
        parts = parts[1:]
    if not parts:
        return None, "missing command after --"
    command = parts[0] if len(parts) == 1 else shlex.join(parts)
    return _sanitize_command(command)


def _write_run_script(session: str, run_id: str, command: str, started_at: float) -> tuple[Path, Path]:
    state = _state_dir(session)
    runs = state / "runs"
    logs = state / "logs"
    scripts = state / "scripts"
    for path in (runs, logs, scripts):
        path.mkdir(parents=True, exist_ok=True)
    log_path = logs / f"{run_id}.log"
    script_path = scripts / f"{run_id}.sh"
    status_path = _status_path(session, run_id)
    active_path = _active_path(session)
    content = f"""#!/usr/bin/env bash
set +e
__tmux_ops_code=0
{{
  (
    set +e
{command}
  )
  __tmux_ops_code=$?
}} > >(tee -a {shlex.quote(str(log_path))}) 2> >(tee -a {shlex.quote(str(log_path))} >&2)
TMUX_OPS_STATUS_PATH={shlex.quote(str(status_path))} \\
TMUX_OPS_SESSION={shlex.quote(session)} \\
TMUX_OPS_RUN_ID={shlex.quote(run_id)} \\
TMUX_OPS_EXIT_CODE="$__tmux_ops_code" \\
TMUX_OPS_STARTED_AT={started_at!r} \\
TMUX_OPS_LOG_PATH={shlex.quote(str(log_path))} \\
TMUX_OPS_SCRIPT_PATH={shlex.quote(str(script_path))} \\
TMUX_OPS_ATTACH={shlex.quote(_attach_command(session))} \\
python3 - <<'PY'
import json, os, time
finished = time.time()
started = float(os.environ["TMUX_OPS_STARTED_AT"])
payload = {{
    "run_id": os.environ["TMUX_OPS_RUN_ID"],
    "session": os.environ["TMUX_OPS_SESSION"],
    "status": "completed",
    "exit_code": int(os.environ["TMUX_OPS_EXIT_CODE"]),
    "started_at": started,
    "finished_at": finished,
    "elapsed_s": round(finished - started, 3),
    "log_path": os.environ["TMUX_OPS_LOG_PATH"],
    "script_path": os.environ["TMUX_OPS_SCRIPT_PATH"],
    "attach_command": os.environ["TMUX_OPS_ATTACH"],
}}
with open(os.environ["TMUX_OPS_STATUS_PATH"], "w", encoding="utf-8") as f:
    json.dump(payload, f, sort_keys=True)
    f.write("\\n")
PY
rm -f {shlex.quote(str(active_path))}
printf '%s\n' {shlex.quote(run_id)} > {shlex.quote(str(_state_dir(session) / "last_run_id"))}
exit "$__tmux_ops_code"
"""
    script_path.write_text(content, encoding="utf-8")
    script_path.chmod(0o700)
    return script_path, log_path


def cmd_run(target: str, command: str, timeout: float, tail_lines: int) -> dict[str, Any]:
    san = _sanitize_session(target)
    if san is None:
        return {"error": "invalid session name", "session": target, "source": "run"}
    ok, err = _ensure_managed_session(san)
    if not ok:
        return {"error": "session is not ready for run", "detail": err or "", "session": san, "source": "run"}
    active = _live_active(san)
    if active:
        return {
            "error": "run already active",
            "detail": "use status or cancel before starting another run",
            **_status_payload(san, str(active.get("run_id", "")), tail_lines),
            "source": "run",
        }

    run_id = f"{int(time.time())}-{uuid.uuid4().hex[:10]}"
    started_at = time.time()
    script_path, log_path = _write_run_script(san, run_id, command, started_at)
    status = {
        "run_id": run_id,
        "session": san,
        "status": "running",
        "exit_code": None,
        "started_at": started_at,
        "elapsed_s": 0.0,
        "log_path": str(log_path),
        "script_path": str(script_path),
        "attach_command": _attach_command(san),
    }
    _json_write(_status_path(san, run_id), status)
    _json_write(_active_path(san), status)

    channel = _run_channel(san, run_id)
    wait = _start_tmux_wait(channel)
    r = _targeted_tmux(san, ["send-keys", "-t", "{target}", f"TMUX_OPS_RUN_ID={shlex.quote(run_id)} bash {shlex.quote(str(script_path))}", "Enter"])
    if r.returncode != 0:
        status.update({"status": "failed", "detail": r.stderr})
        _json_write(_status_path(san, run_id), status)
        try:
            _active_path(san).unlink()
        except OSError:
            pass
        return {"error": "tmux send-keys failed", "detail": r.stderr, **_status_payload(san, run_id, tail_lines), "source": "run"}

    completed = _wait_proc(wait, timeout)
    if completed:
        out = _status_payload(san, run_id, tail_lines)
        if out.get("status") == "running":
            out["elapsed_s"] = round(time.time() - started_at, 3)
        return out

    out = _status_payload(san, run_id, tail_lines)
    if out.get("status") == "running":
        out["elapsed_s"] = round(time.time() - started_at, 3)
    return out


def cmd_status(target: str, run_id: str | None, wait: bool, timeout: float, tail_lines: int) -> dict[str, Any]:
    san = _sanitize_session(target)
    if san is None:
        return {"error": "invalid session name", "session": target, "source": "status"}
    active = _live_active(san)
    rid = run_id or (str(active.get("run_id")) if active else None)
    if rid is None:
        return {"session": san, "status": "idle", "attach_command": _attach_command(san), "tail": ""}
    status = _status_payload(san, rid, tail_lines)
    if wait and status.get("status") == "running":
        proc = _start_tmux_wait(_run_channel(san, rid))
        _wait_proc(proc, timeout)
        status = _status_payload(san, rid, tail_lines)
        if status.get("status") == "running":
            status["elapsed_s"] = round(time.time() - float(status.get("started_at", time.time())), 3)
    return status


def cmd_cancel(target: str, run_id: str) -> dict[str, Any]:
    san = _sanitize_session(target)
    if san is None:
        return {"error": "invalid session name", "session": target, "source": "cancel"}
    active = _live_active(san)
    if not active:
        return {"error": "no active run", "session": san, "source": "cancel"}
    if active.get("run_id") != run_id:
        return {"error": "run_id does not match active run", "session": san, "run_id": run_id, "source": "cancel"}
    r = _targeted_tmux(san, ["send-keys", "-t", "{target}", "C-c"])
    if r.returncode != 0:
        return {"error": "tmux cancel failed", "detail": r.stderr, "session": san, "run_id": run_id, "source": "cancel"}
    status = _status_payload(san, run_id)
    status["cancel_sent"] = True
    status["status"] = "running"
    return status


def cmd_wait(
    target: str,
    timeout: float = DEFAULT_WAIT_TIMEOUT,
    idle_re: re.Pattern[str] | None = None,
    pre_cursor_y: int | None = None,
) -> dict[str, Any]:
    san = _sanitize_session(target)
    if san is None:
        return {"error": "invalid session name", "session": target, "source": "wait"}

    pattern = idle_re or IDLE_PROMPT_RE
    start = time.monotonic()
    polls = 0
    while True:
        elapsed = time.monotonic() - start
        if elapsed >= timeout:
            cy, _ = _cursor_y(san)
            cursor_line = ""
            if cy is not None:
                cursor_line, _ = _capture_line(san, cy)
            return {
                "session": san,
                "idle": False,
                "elapsed_s": round(elapsed, 3),
                "polls": polls,
                "timed_out": True,
                "cursor_line": cursor_line,
            }
        interval = FAST_POLL_INTERVAL if elapsed < FAST_PHASE_DURATION else MED_POLL_INTERVAL if elapsed < MED_PHASE_DURATION else SLOW_POLL_INTERVAL
        time.sleep(interval)
        polls += 1
        cy, _ = _cursor_y(san)
        if cy is None:
            continue
        if pre_cursor_y is not None and cy == pre_cursor_y:
            continue
        line, _ = _capture_line(san, cy)
        if pattern.match(line):
            return {"session": san, "idle": True, "elapsed_s": round(time.monotonic() - start, 3), "polls": polls}


def cmd_send(
    target: str,
    command: str,
    delay: float | None = None,
    wait: bool = False,
    wait_timeout: float = DEFAULT_WAIT_TIMEOUT,
    idle_re: re.Pattern[str] | None = None,
) -> dict[str, Any]:
    san = _sanitize_session(target)
    if san is None:
        return {"error": "invalid session name", "session": target, "source": "send"}
    cmd, cmd_err = _sanitize_command(command)
    if cmd_err is not None:
        return {"error": "invalid command", "detail": cmd_err, "session": san, "source": "send"}
    if delay is None:
        try:
            delay = float(os.environ.get("TMUX_OPS_SEND_DELAY", str(DEFAULT_SEND_DELAY)))
        except ValueError:
            delay = DEFAULT_SEND_DELAY
    if delay < 0:
        return {"error": "delay must be non-negative", "detail": str(delay), "session": san, "source": "send"}
    pre_cy = _snapshot_cursor(san)
    r = _targeted_tmux(san, ["send-keys", "-t", "{target}", cmd, "Enter"])
    if r.returncode != 0:
        return {"error": "tmux send-keys failed", "detail": r.stderr, "session": san, "source": "send"}
    time.sleep(delay)
    result: dict[str, Any] = {"session": san, "sent": True, "delay_s": delay}
    if wait:
        w = cmd_wait(san, wait_timeout, idle_re, pre_cursor_y=pre_cy)
        result.update({k: v for k, v in w.items() if k != "session"})
    return result


def _emit_error(out: dict[str, Any]) -> None:
    err = out.get("error", "unknown error")
    detail = out.get("detail", "")
    source = out.get("source", "")
    parts = [f"tmux_ops: {err}"]
    if detail:
        parts.append(f" detail={detail}")
    if source:
        parts.append(f" source={source}")
    sys.stderr.write("".join(parts) + "\n")


def main() -> int:
    try:
        parser = argparse.ArgumentParser(description="Managed tmux ops: pick, probe, run, status, cancel.")
        subparsers = parser.add_subparsers(dest="command", required=True)

        subparsers.add_parser("pick", help="Pick or create the first safe managed ops session")

        probe_p = subparsers.add_parser("probe", help="Check sudo readiness without fixed sleeps")
        probe_p.add_argument("-t", "--target", required=True, metavar="SESSION")

        run_p = subparsers.add_parser("run", help="Run a command in a managed tmux session")
        run_p.add_argument("-t", "--target", required=True, metavar="SESSION")
        run_p.add_argument("--timeout", type=float, default=DEFAULT_RUN_TIMEOUT, metavar="SECS")
        run_p.add_argument("--tail", type=int, default=DEFAULT_TAIL_LINES, metavar="N")
        run_p.add_argument("cmd", nargs=argparse.REMAINDER, metavar="-- CMD")

        status_p = subparsers.add_parser("status", help="Report active or completed run status")
        status_p.add_argument("-t", "--target", required=True, metavar="SESSION")
        status_p.add_argument("--run-id", default=None, metavar="ID")
        status_p.add_argument("--wait", action="store_true", default=False)
        status_p.add_argument("--timeout", type=float, default=DEFAULT_WAIT_TIMEOUT, metavar="SECS")
        status_p.add_argument("--tail", type=int, default=DEFAULT_TAIL_LINES, metavar="N")

        cancel_p = subparsers.add_parser("cancel", help="Interrupt the active managed run")
        cancel_p.add_argument("-t", "--target", required=True, metavar="SESSION")
        cancel_p.add_argument("--run-id", required=True, metavar="ID")

        send_p = subparsers.add_parser("send", help="Legacy: send one command to pane")
        send_p.add_argument("-t", "--target", required=True, metavar="SESSION")
        send_p.add_argument("-d", "--delay", type=float, default=None, metavar="SECS")
        send_p.add_argument("--wait", action="store_true", default=False)
        send_p.add_argument("--wait-timeout", type=float, default=DEFAULT_WAIT_TIMEOUT, metavar="SECS")
        send_p.add_argument("--idle-re", default=None, metavar="PATTERN")
        send_p.add_argument("cmd", nargs=1, metavar="CMD")

        wait_p = subparsers.add_parser("wait", help="Legacy: poll pane until prompt idle or timeout")
        wait_p.add_argument("-t", "--target", required=True, metavar="SESSION")
        wait_p.add_argument("--timeout", type=float, default=DEFAULT_WAIT_TIMEOUT, metavar="SECS")
        wait_p.add_argument("--idle-re", default=None, metavar="PATTERN")
        wait_p.add_argument("--pre-cursor-y", type=int, default=None, metavar="N")

        args = parser.parse_args()

        if args.command == "pick":
            out = cmd_pick()
        elif args.command == "probe":
            out = cmd_probe(args.target)
        elif args.command == "run":
            cmd, cmd_err = _command_from_remainder(args.cmd)
            out = {"error": "invalid command", "detail": cmd_err, "source": "run"} if cmd_err else cmd_run(args.target, cmd or "", args.timeout, args.tail)
        elif args.command == "status":
            out = cmd_status(args.target, args.run_id, args.wait, args.timeout, args.tail)
        elif args.command == "cancel":
            out = cmd_cancel(args.target, args.run_id)
        elif args.command == "send":
            idle_re, re_err = _compile_idle_re(args.idle_re)
            out = {"error": "invalid --idle-re pattern", "detail": re_err, "source": "send"} if re_err else cmd_send(
                args.target,
                args.cmd[0],
                args.delay,
                wait=args.wait,
                wait_timeout=args.wait_timeout,
                idle_re=idle_re,
            )
        elif args.command == "wait":
            idle_re, re_err = _compile_idle_re(args.idle_re)
            out = {"error": "invalid --idle-re pattern", "detail": re_err, "source": "wait"} if re_err else cmd_wait(
                args.target,
                timeout=args.timeout,
                idle_re=idle_re,
                pre_cursor_y=args.pre_cursor_y,
            )
        else:
            out = {"error": "unknown command", "source": "main"}

        if "error" in out:
            _emit_error(out)
        print(json.dumps(out))
        return 0 if "error" not in out else 1
    except Exception as e:
        err_payload = {
            "error": "unexpected exception",
            "exception_type": type(e).__name__,
            "exception_message": str(e),
            "source": "main",
        }
        _emit_error(err_payload)
        print(json.dumps(err_payload))
        if os.environ.get("LOCALSETUP_DEBUG"):
            import traceback
            sys.stderr.write(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
