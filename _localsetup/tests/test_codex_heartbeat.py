import json
import sys
from pathlib import Path

import pytest

from _localsetup.tests.codex_heartbeat_test_helpers import load_runtime, state_root, write_config


def test_heartbeat_transaction_promotes_valid_no_agent_run(tmp_path: Path) -> None:
    runtime = load_runtime()
    target = tmp_path / "repo"
    target.mkdir()
    write_config(target)

    payload = runtime.run_once(target_root=target, no_agent=True)

    assert payload["ok"] is True
    latest = json.loads((state_root(target) / "latest.json").read_text(encoding="utf-8"))
    run_dir = state_root(target) / latest["path"]
    assert run_dir.is_dir()
    assert (run_dir / "manifest.json").is_file()
    assert (run_dir / "heartbeat-result.json").is_file()
    assert (run_dir / "command-log.json").is_file()
    assert not (state_root(target) / "active.json").exists()


def test_heartbeat_validates_staged_artifacts_before_promotion(tmp_path: Path) -> None:
    runtime = load_runtime()
    target = tmp_path / "repo"
    target.mkdir()
    root = state_root(target)
    staged = root / "runs" / "bad.staged"
    staged.mkdir(parents=True)
    (staged / "heartbeat-result.json").write_text("{}\n", encoding="utf-8")
    (staged / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": runtime.SCHEMA_VERSION,
                "run_id": "bad",
                "status": "succeeded",
                "artifacts": {"heartbeat-result.json": "not-the-real-hash"},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(runtime.HeartbeatError, match="hash mismatch"):
        runtime.promote_staged_run(staged, root)
    assert not (root / "latest.json").exists()


def test_heartbeat_captures_command_output_sidecars(tmp_path: Path) -> None:
    runtime = load_runtime()
    target = tmp_path / "repo"
    target.mkdir()
    write_config(
        target,
        hooks={
            "before": [
                {
                    "id": "hello",
                    "command": [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr)"],
                    "timeout_seconds": 5,
                }
            ],
            "after": [],
        },
    )

    payload = runtime.run_once(target_root=target, no_agent=True)

    assert payload["ok"] is True
    latest = json.loads((state_root(target) / "latest.json").read_text(encoding="utf-8"))
    command_log = json.loads((state_root(target) / latest["path"] / "command-log.json").read_text(encoding="utf-8"))
    entry = command_log["commands"][0]
    assert entry["returncode"] == 0
    assert "out" in entry["stdout_tail"]
    assert "err" in entry["stderr_tail"]
    assert (state_root(target) / latest["path"] / entry["sidecar"]).is_file()


def test_heartbeat_resolved_path_launcher_finds_codex_in_controlled_path(tmp_path: Path) -> None:
    runtime = load_runtime()
    target = tmp_path / "repo"
    target.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_codex = fake_bin / "codex"
    fake_codex.write_text("#!/bin/sh\nprintf 'fake codex %s\\n' \"$1\"\n", encoding="utf-8")
    fake_codex.chmod(0o755)
    write_config(
        target,
        codex={"enabled": True, "profile": "heartbeat", "timeout_seconds": 5},
        agent_profiles={
            "heartbeat": {
                "app": "codex",
                "launcher": "resolved-path",
                "command_name": "codex",
                "path": [str(fake_bin)],
                "model_policy": "configurable-low-cost",
                "model": None,
                "reasoning_effort": "low",
                "json": True,
                "prompt": "status",
            }
        },
    )

    payload = runtime.run_once(target_root=target)

    assert payload["ok"] is True
    latest = json.loads((state_root(target) / "latest.json").read_text(encoding="utf-8"))
    command_log = json.loads((state_root(target) / latest["path"] / "command-log.json").read_text(encoding="utf-8"))
    entry = command_log["commands"][0]
    assert entry["launcher_mode"] == "resolved-path"
    assert entry["resolved_executable"] == str(fake_codex)
    assert entry["argv"][0] == str(fake_codex)
    assert entry["model_policy"] == "configurable-low-cost"
    assert entry["timeout_seconds"] == 5


def test_heartbeat_direct_argv_launcher_preserves_explicit_command(tmp_path: Path) -> None:
    runtime = load_runtime()
    target = tmp_path / "repo"
    target.mkdir()
    command = [sys.executable, "-c", "print('direct profile')"]
    write_config(
        target,
        codex={"enabled": True, "profile": "heartbeat", "timeout_seconds": 5},
        agent_profiles={
            "heartbeat": {
                "app": "codex",
                "launcher": "direct-argv",
                "command": command,
                "model_policy": "test-direct",
                "json": False,
            }
        },
    )

    payload = runtime.run_once(target_root=target)

    assert payload["ok"] is True
    latest = json.loads((state_root(target) / "latest.json").read_text(encoding="utf-8"))
    command_log = json.loads((state_root(target) / latest["path"] / "command-log.json").read_text(encoding="utf-8"))
    entry = command_log["commands"][0]
    assert entry["launcher_mode"] == "direct-argv"
    assert entry["logical_argv"] == command
    assert "direct profile" in entry["stdout_tail"]


def test_heartbeat_shell_login_launcher_is_opt_in_and_records_rendered_command(tmp_path: Path) -> None:
    runtime = load_runtime()
    target = tmp_path / "repo"
    target.mkdir()
    command = [sys.executable, "-c", "print('shell profile')"]
    write_config(
        target,
        codex={"enabled": True, "profile": "heartbeat", "timeout_seconds": 5},
        agent_profiles={
            "heartbeat": {
                "app": "codex",
                "launcher": "shell-login",
                "command": command,
                "model_policy": "test-shell",
                "json": False,
            }
        },
    )

    payload = runtime.run_once(target_root=target)

    assert payload["ok"] is True
    latest = json.loads((state_root(target) / "latest.json").read_text(encoding="utf-8"))
    command_log = json.loads((state_root(target) / latest["path"] / "command-log.json").read_text(encoding="utf-8"))
    entry = command_log["commands"][0]
    assert entry["launcher_mode"] == "shell-login"
    assert "rendered_command" in entry
    assert shlex_join_safe(command[0]) in entry["rendered_command"]
    assert "shell profile" in entry["stdout_tail"]


def test_heartbeat_sidecar_filename_ignores_malicious_hook_id(tmp_path: Path) -> None:
    runtime = load_runtime()
    target = tmp_path / "repo"
    target.mkdir()
    write_config(
        target,
        hooks={
            "before": [{"id": "../../../../escape", "command": [sys.executable, "-c", "print('safe')"], "timeout_seconds": 5}],
            "after": [],
        },
    )

    payload = runtime.run_once(target_root=target, no_agent=True)

    assert payload["ok"] is True
    latest = json.loads((state_root(target) / "latest.json").read_text(encoding="utf-8"))
    run_dir = state_root(target) / latest["path"]
    command_log = json.loads((run_dir / "command-log.json").read_text(encoding="utf-8"))
    entry = command_log["commands"][0]
    assert entry["id"] == "../../../../escape"
    assert entry["sidecar"] == "command-01.json"
    assert (run_dir / entry["sidecar"]).is_file()
    assert not (target / "escape.json").exists()
    assert not (target / "escape").exists()


def test_heartbeat_sidecar_filename_ignores_malicious_profile_name(tmp_path: Path) -> None:
    runtime = load_runtime()
    target = tmp_path / "repo"
    target.mkdir()
    profile_name = "../../../../escape"
    command = [sys.executable, "-c", "print('profile safe')"]
    write_config(
        target,
        codex={"enabled": True, "profile": profile_name, "timeout_seconds": 5},
        agent_profiles={
            profile_name: {
                "app": "codex",
                "launcher": "direct-argv",
                "command": command,
                "model_policy": "test-direct",
                "json": False,
            }
        },
    )

    payload = runtime.run_once(target_root=target)

    assert payload["ok"] is True
    latest = json.loads((state_root(target) / "latest.json").read_text(encoding="utf-8"))
    run_dir = state_root(target) / latest["path"]
    command_log = json.loads((run_dir / "command-log.json").read_text(encoding="utf-8"))
    entry = command_log["commands"][0]
    assert entry["id"] == f"{profile_name}-agent"
    assert entry["sidecar"] == "command-01.json"
    assert (run_dir / entry["sidecar"]).is_file()
    assert not (target / "escape-agent.json").exists()
    assert not (target / "escape-agent").exists()


def shlex_join_safe(value: str) -> str:
    import shlex

    return shlex.quote(value)


def test_heartbeat_lock_held_reports_locked(tmp_path: Path) -> None:
    runtime = load_runtime()
    target = tmp_path / "repo"
    target.mkdir()
    write_config(target)
    root = state_root(target)
    root.mkdir(parents=True)
    (root / "heartbeat.lock").write_text('{"pid": 12345}\n', encoding="utf-8")

    payload = runtime.run_once(target_root=target, no_agent=True)

    assert payload["ok"] is False
    assert payload["status"] == "locked"
    assert payload["lock"]["pid"] == 12345


def test_heartbeat_recovers_stale_staged_runs_before_new_run(tmp_path: Path) -> None:
    runtime = load_runtime()
    target = tmp_path / "repo"
    target.mkdir()
    write_config(target)
    staged = state_root(target) / "runs" / "old.staged"
    staged.mkdir(parents=True)
    (staged / "manifest.json").write_text('{"run_id": "old", "status": "running"}\n', encoding="utf-8")

    payload = runtime.run_once(target_root=target, no_agent=True)

    assert payload["ok"] is True
    recovered = list((state_root(target) / "runs").glob("old.recovered-*"))
    assert len(recovered) == 1
    recovered_manifest = json.loads((recovered[0] / "manifest.json").read_text(encoding="utf-8"))
    assert recovered_manifest["status"] == "failed_recovered"
    assert payload["manifest"]["recovered_before_run"][0]["status"] == "failed_recovered"


def test_heartbeat_rejects_unsafe_active_pointer(tmp_path: Path) -> None:
    runtime = load_runtime()
    target = tmp_path / "repo"
    target.mkdir()
    write_config(target)
    root = state_root(target)
    root.mkdir(parents=True)
    (root / "active.json").write_text('{"path": "../../escape"}\n', encoding="utf-8")

    payload = runtime.status(target_root=target)

    assert payload["ok"] is False
    assert any("pointer path" in issue for issue in payload["issues"])


def test_heartbeat_timeout_records_failed_run(tmp_path: Path) -> None:
    runtime = load_runtime()
    target = tmp_path / "repo"
    target.mkdir()
    write_config(
        target,
        hooks={
            "before": [
                {
                    "id": "slow",
                    "command": [sys.executable, "-c", "import time; time.sleep(2)"],
                    "timeout_seconds": 1,
                }
            ],
            "after": [],
        },
    )

    payload = runtime.run_once(target_root=target, no_agent=True)

    assert payload["ok"] is False
    assert payload["status"] == "failed"
    latest = json.loads((state_root(target) / "latest.json").read_text(encoding="utf-8"))
    command_log = json.loads((state_root(target) / latest["path"] / "command-log.json").read_text(encoding="utf-8"))
    assert command_log["commands"][0]["returncode"] == 124
    assert command_log["commands"][0]["timed_out"] is True


def test_heartbeat_direct_command_policy_blocks_git_writes(tmp_path: Path) -> None:
    runtime = load_runtime()
    target = tmp_path / "repo"
    target.mkdir()
    write_config(
        target,
        hooks={
            "before": [{"id": "git-push", "command": ["git", "push"], "timeout_seconds": 5}],
            "after": [],
        },
    )

    payload = runtime.run_once(target_root=target, no_agent=True)

    assert payload["ok"] is False
    latest = json.loads((state_root(target) / "latest.json").read_text(encoding="utf-8"))
    command_log = json.loads((state_root(target) / latest["path"] / "command-log.json").read_text(encoding="utf-8"))
    assert command_log["commands"][0]["blocked"] is True
    assert "git push" in command_log["commands"][0]["error"]


def test_heartbeat_direct_command_policy_blocks_destructive_hooks(tmp_path: Path) -> None:
    runtime = load_runtime()
    target = tmp_path / "repo"
    target.mkdir()
    write_config(
        target,
        hooks={
            "before": [{"id": "remove", "command": ["rm", "-rf", "tmp"], "timeout_seconds": 5}],
            "after": [],
        },
    )

    payload = runtime.run_once(target_root=target, no_agent=True)

    assert payload["ok"] is False
    latest = json.loads((state_root(target) / "latest.json").read_text(encoding="utf-8"))
    command_log = json.loads((state_root(target) / latest["path"] / "command-log.json").read_text(encoding="utf-8"))
    assert command_log["commands"][0]["blocked"] is True
    assert "destructive executable" in command_log["commands"][0]["error"]
