import json
import os
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
    env, _socket = tmux_env
    run_ops(env, "pick")

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

    _, status = run_ops(env, "status", "-t", "ops", "--run-id", payload["run_id"], "--tail", "20")
    assert status["status"] == "completed"
    assert status["exit_code"] == 7


def test_run_timeout_stays_active_and_blocks_second_run(tmux_env):
    env, _socket = tmux_env
    run_ops(env, "pick")

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
            probe = run_ops(env, "probe", "-t", pick["session"])[1]
            assert probe["sudo"] == expected
            assert probe["attach_command"] == "tmux new-session -A -s ops"
        finally:
            subprocess.run(["tmux", "-L", socket, "kill-server"], capture_output=True, text=True)


def test_skill_documents_managed_run_path():
    skill = (ROOT / "_localsetup" / "skills" / "ls-tmux-shared-session-workflow" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "tmux send-keys" not in skill
    assert "tmux_ops run" in skill
    sequence = skill.split("## Sequence", 1)[1].split("## Output Contract", 1)[0]
    assert "pick" in sequence
    assert "probe" in sequence
    assert "run" in sequence
    assert "send -t" not in sequence
