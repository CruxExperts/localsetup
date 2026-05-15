import json
import os
import shlex
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "_localsetup" / "tools" / "tmux_ops.py"


@pytest.fixture
def tmux_env(tmp_path):
    if shutil.which("tmux") is None:
        pytest.skip("tmux is not installed")
    socket = f"localsetup-test-{uuid.uuid4().hex}"
    env = os.environ.copy()
    env["TMUX_OPS_TMUX"] = f"tmux -L {socket}"
    env["TMUX_OPS_STATE_ROOT"] = str(tmp_path / "state")
    try:
        yield env, socket
    finally:
        subprocess.run(["tmux", "-L", socket, "kill-server"], capture_output=True, text=True)


def run_ops(env, *args, check=True):
    proc = subprocess.run(
        [sys.executable, str(TOOL), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if check and proc.returncode != 0:
        raise AssertionError(f"tmux_ops failed: stdout={proc.stdout!r} stderr={proc.stderr!r}")
    payload = json.loads(proc.stdout)
    return proc, payload


def install_tmux_wrapper(tmp_path, env, socket, *, fail_run_send=False):
    log_path = tmp_path / f"tmux-{uuid.uuid4().hex}.log"
    wrapper = tmp_path / f"tmux-wrapper-{uuid.uuid4().hex}"
    fail_flag = "1" if fail_run_send else "0"
    wrapper.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
log={shlex.quote(str(log_path))}
fail_run_send={fail_flag}
printf '%q ' "$@" >> "$log"
printf '\\n' >> "$log"
if [ "$fail_run_send" = "1" ] && [ "${{1:-}}" = "send-keys" ]; then
  for arg in "$@"; do
    case "$arg" in
      TMUX_OPS_RUN_ID=*) printf 'not in a mode\\n' >&2; exit 1 ;;
    esac
  done
fi
exec tmux -L {shlex.quote(socket)} "$@"
""",
        encoding="utf-8",
    )
    wrapper.chmod(0o700)
    env["TMUX_OPS_TMUX"] = str(wrapper)
    return log_path


def tmux_calls(log_path):
    if not log_path.exists():
        return []
    return [shlex.split(line) for line in log_path.read_text(encoding="utf-8").splitlines()]


def send_targets(log_path, *, contains=None):
    targets = []
    for call in tmux_calls(log_path):
        if not call or call[0] != "send-keys":
            continue
        if contains is not None and not any(contains in part for part in call):
            continue
        targets.append(call[call.index("-t") + 1])
    return targets


def test_pick_creates_real_managed_session(tmux_env):
    env, socket = tmux_env

    _, payload = run_ops(env, "pick")

    assert payload["session"] == "ops"
    assert payload["reason"] == "created"
    assert payload["attach_command"] == "tmux new-session -A -s ops"
    has_session = subprocess.run(
        ["tmux", "-L", socket, "has-session", "-t", "ops"],
        capture_output=True,
        text=True,
    )
    assert has_session.returncode == 0


def test_run_captures_output_and_preserves_nonzero_exit(tmux_env):
    env, socket = tmux_env
    log_path = install_tmux_wrapper(Path(env["TMUX_OPS_STATE_ROOT"]).parent, env, socket)
    run_ops(env, "pick")
    log_path.write_text("", encoding="utf-8")

    _, payload = run_ops(
        env,
        "run",
        "-t",
        "ops",
        "--timeout",
        "5",
        "--tail",
        "20",
        "--",
        "bash",
        "-lc",
        "echo stdout; echo stderr >&2; exit 7",
    )

    assert payload["status"] == "completed"
    assert payload["exit_code"] == 7
    assert "stdout" in payload["tail"]
    assert "stderr" in payload["tail"]
    assert Path(payload["log_path"]).exists()
    assert send_targets(log_path, contains="TMUX_OPS_RUN_ID=")
    assert all(target.startswith("%") for target in send_targets(log_path, contains="TMUX_OPS_RUN_ID="))

    _, status = run_ops(env, "status", "-t", "ops", "--run-id", payload["run_id"], "--tail", "20")
    assert status["status"] == "completed"
    assert status["exit_code"] == 7


def test_run_timeout_stays_active_and_blocks_second_run(tmux_env):
    env, socket = tmux_env
    log_path = install_tmux_wrapper(Path(env["TMUX_OPS_STATE_ROOT"]).parent, env, socket)
    run_ops(env, "pick")
    log_path.write_text("", encoding="utf-8")

    _, first = run_ops(
        env,
        "run",
        "-t",
        "ops",
        "--timeout",
        "0.2",
        "--tail",
        "20",
        "--",
        "bash",
        "-lc",
        "echo start; sleep 1; echo done",
    )

    assert first["status"] == "running"
    assert first["exit_code"] is None
    assert "start" in first["tail"]
    assert all(target.startswith("%") for target in send_targets(log_path, contains="TMUX_OPS_RUN_ID="))

    proc, blocked = run_ops(env, "run", "-t", "ops", "--", "echo", "blocked", check=False)
    assert proc.returncode == 1
    assert blocked["error"] == "run already active"
    assert blocked["run_id"] == first["run_id"]

    _, completed = run_ops(
        env,
        "status",
        "-t",
        "ops",
        "--run-id",
        first["run_id"],
        "--wait",
        "--timeout",
        "3",
        "--tail",
        "20",
    )
    assert completed["status"] == "completed"
    assert completed["exit_code"] == 0
    assert "done" in completed["tail"]


def test_probe_classifies_sudo_states(tmux_env, tmp_path):
    env, _socket = tmux_env
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    sudo = fake_bin / "sudo"
    sudo.write_text(
        """#!/usr/bin/env bash
case "${FAKE_SUDO_MODE:-ready}:$1" in
  ready:-vn) exit 0 ;;
  password:-vn) echo "sudo: a password is required" >&2; exit 1 ;;
  failed:-vn) echo "testuser is not in the sudoers file" >&2; exit 1 ;;
  password:-v) echo "[sudo] password for testuser:" >&2; sleep 30 ;;
  *) exit 1 ;;
esac
""",
        encoding="utf-8",
    )
    sudo.chmod(0o700)
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"

    for mode, expected in [
        ("ready", "ready"),
        ("password", "password_required"),
        ("failed", "failed"),
    ]:
        env["FAKE_SUDO_MODE"] = mode
        socket = f"localsetup-test-{uuid.uuid4().hex}"
        env["TMUX_OPS_TMUX"] = f"tmux -L {socket}"
        env["TMUX_OPS_STATE_ROOT"] = str(tmp_path / f"state-{mode}")
        try:
            pick = run_ops(env, "pick")[1]
            log_path = install_tmux_wrapper(tmp_path, env, socket)
            probe = run_ops(env, "probe", "-t", pick["session"])[1]
            assert probe["sudo"] == expected
            assert probe["attach_command"] == "tmux new-session -A -s ops"
            assert send_targets(log_path, contains="probe.sh")
            assert all(target.startswith("%") for target in send_targets(log_path, contains="probe.sh"))
        finally:
            subprocess.run(["tmux", "-L", socket, "kill-server"], capture_output=True, text=True)


def test_cancel_uses_resolved_pane_target(tmux_env):
    env, socket = tmux_env
    log_path = install_tmux_wrapper(Path(env["TMUX_OPS_STATE_ROOT"]).parent, env, socket)
    run_ops(env, "pick")
    _, run_payload = run_ops(
        env,
        "run",
        "-t",
        "ops",
        "--timeout",
        "0.2",
        "--tail",
        "5",
        "--",
        "bash",
        "-lc",
        "sleep 5",
    )
    assert run_payload["status"] == "running"
    log_path.write_text("", encoding="utf-8")

    _, cancel = run_ops(env, "cancel", "-t", "ops", "--run-id", run_payload["run_id"])

    assert cancel["cancel_sent"] is True
    assert send_targets(log_path, contains="C-c")
    assert all(target.startswith("%") for target in send_targets(log_path, contains="C-c"))


def test_legacy_send_uses_resolved_pane_target(tmux_env):
    env, socket = tmux_env
    log_path = install_tmux_wrapper(Path(env["TMUX_OPS_STATE_ROOT"]).parent, env, socket)
    run_ops(env, "pick")
    log_path.write_text("", encoding="utf-8")

    _, payload = run_ops(env, "send", "-t", "ops", "--wait", "--wait-timeout", "3", "echo legacy-send-ok")

    assert payload["sent"] is True
    assert send_targets(log_path, contains="echo legacy-send-ok")
    assert all(target.startswith("%") for target in send_targets(log_path, contains="echo legacy-send-ok"))


def test_run_send_keys_failure_reports_resolved_pane_target(tmux_env):
    env, socket = tmux_env
    tmp_path = Path(env["TMUX_OPS_STATE_ROOT"]).parent
    install_tmux_wrapper(tmp_path, env, socket)
    run_ops(env, "pick")
    install_tmux_wrapper(tmp_path, env, socket, fail_run_send=True)

    proc, payload = run_ops(env, "run", "-t", "ops", "--", "echo", "blocked", check=False)

    assert proc.returncode == 1
    assert payload["error"] == "tmux send-keys failed"
    assert "not in a mode" in payload["detail"]
    assert "resolved_target=%" in payload["detail"]


def test_skill_documents_managed_run_path():
    skill = (ROOT / "_localsetup" / "workflows" / "ls-workflow-ops-tmux-session" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "tmux send-keys" not in skill
    assert "tmux_ops run" in skill
    sequence = skill.split("## Sequence", 1)[1]
    assert "pick" in sequence
    assert "probe" in sequence
    assert "run" in sequence
    assert "send -t" not in sequence
