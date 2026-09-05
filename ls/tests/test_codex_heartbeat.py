import json
import sys
from pathlib import Path

import pytest

from ls.tests.codex_heartbeat_test_helpers import load_runtime, state_root, write_config


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
    (staged / "command-log.json").write_text('{"commands": []}\n', encoding="utf-8")
    (staged / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": runtime.SCHEMA_VERSION,
                "run_id": "bad",
                "status": "succeeded",
                "artifacts": {
                    "heartbeat-result.json": "not-the-real-hash",
                    "command-log.json": runtime.sha256_file(staged / "command-log.json"),
                },
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


def test_heartbeat_resolved_path_launcher_supports_configured_client(tmp_path: Path) -> None:
    runtime = load_runtime()
    target = tmp_path / "repo"
    target.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_client = fake_bin / "agent-cli"
    fake_client.write_text("#!/bin/sh\nprintf 'fake client %s\n' \"$1\"\n", encoding="utf-8")
    fake_client.chmod(0o755)
    write_config(
        target,
        agent={"enabled": True, "profile": "heartbeat", "timeout_seconds": 5},
        agent_profiles={
            "heartbeat": {
                "client": "future-agent-cli",
                "launcher": "resolved-path",
                "command": ["agent-cli", "{heartbeat_prompt}"],
                "path": [str(fake_bin)],
                "prompt": "status",
            }
        },
    )

    payload = runtime.run_once(target_root=target)

    assert payload["ok"] is True
    latest = json.loads((state_root(target) / "latest.json").read_text(encoding="utf-8"))
    command_log = json.loads((state_root(target) / latest["path"] / "command-log.json").read_text(encoding="utf-8"))
    entry = command_log["commands"][0]
    assert entry["client"] == "future-agent-cli"
    assert entry["launcher_mode"] == "resolved-path"
    assert entry["resolved_executable"] == str(fake_client)
    assert entry["argv"][0] == str(fake_client)
    assert entry["timeout_seconds"] == 5


def test_heartbeat_stdin_prompt_transport_reaches_configured_client(tmp_path: Path) -> None:
    runtime = load_runtime()
    target = tmp_path / "repo"
    target.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_client = fake_bin / "stdin-client"
    fake_client.write_text("#!/bin/sh\ncat\n", encoding="utf-8")
    fake_client.chmod(0o755)
    write_config(
        target,
        agent={"enabled": True, "profile": "heartbeat", "timeout_seconds": 5},
        agent_profiles={
            "heartbeat": {
                "client": "stdin-client",
                "launcher": "resolved-path",
                "command": ["stdin-client"],
                "path": [str(fake_bin)],
                "prompt_transport": "stdin",
                "prompt": "stdin status",
            }
        },
    )

    payload = runtime.run_once(target_root=target)

    assert payload["ok"] is True
    run_dir = state_root(target) / payload["latest"]["path"]
    entry = json.loads((run_dir / "command-log.json").read_text(encoding="utf-8"))["commands"][0]
    assert entry["prompt_transport"] == "stdin"
    assert entry["stdout_tail"] == "stdin status"


def test_heartbeat_direct_argv_launcher_preserves_explicit_command(tmp_path: Path) -> None:
    runtime = load_runtime()
    target = tmp_path / "repo"
    target.mkdir()
    command = [sys.executable, "-c", "print('direct profile')"]
    write_config(
        target,
        agent={"enabled": True, "profile": "heartbeat", "timeout_seconds": 5},
        agent_profiles={
            "heartbeat": {
                "client": "kilo",
                "launcher": "direct-argv",
                "command": command,
                "prompt_transport": "none",
            }
        },
    )

    payload = runtime.run_once(target_root=target)

    assert payload["ok"] is True
    latest = json.loads((state_root(target) / "latest.json").read_text(encoding="utf-8"))
    command_log = json.loads((state_root(target) / latest["path"] / "command-log.json").read_text(encoding="utf-8"))
    entry = command_log["commands"][0]
    assert entry["client"] == "kilo"
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
        agent={"enabled": True, "profile": "heartbeat", "timeout_seconds": 5},
        agent_profiles={
            "heartbeat": {
                "client": "openclaw",
                "launcher": "shell-login",
                "command": command,
                "prompt_transport": "none",
            }
        },
    )

    payload = runtime.run_once(target_root=target)

    assert payload["ok"] is True
    latest = json.loads((state_root(target) / "latest.json").read_text(encoding="utf-8"))
    command_log = json.loads((state_root(target) / latest["path"] / "command-log.json").read_text(encoding="utf-8"))
    entry = command_log["commands"][0]
    assert entry["client"] == "openclaw"
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
        agent={"enabled": True, "profile": profile_name, "timeout_seconds": 5},
        agent_profiles={
            profile_name: {
                "client": "gemini",
                "launcher": "direct-argv",
                "command": command,
                "prompt_transport": "none",
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


def test_heartbeat_reclaims_only_proven_stale_locks(tmp_path: Path) -> None:
    runtime = load_runtime()
    target = tmp_path / "repo"
    target.mkdir()
    write_config(target)
    root = state_root(target)
    root.mkdir(parents=True)
    stale_owner = {
        "created_at": "2000-01-01T00:00:00Z",
        "hostname": runtime._current_hostname(),
        "pid": 999_999_999,
    }
    (root / "heartbeat.lock").write_text(json.dumps(stale_owner), encoding="utf-8")

    payload = runtime.run_once(target_root=target, no_agent=True)

    assert payload["ok"] is True
    assert not list(root.glob("heartbeat.lock.recovered-*"))
    assert not (root / "heartbeat.lock").exists()


def test_heartbeat_stale_lock_retries_until_contender_owner_is_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = load_runtime()
    root = state_root(tmp_path / "repo")
    root.mkdir(parents=True)
    lock_path = root / "heartbeat.lock"
    stale_owner = {"created_at": "2000-01-01T00:00:00Z", "hostname": runtime._current_hostname(), "pid": 999_999_999}
    contender_owner = {"created_at": "2026-01-01T00:00:00Z", "hostname": runtime._current_hostname(), "pid": 1}
    lock_path.write_text(json.dumps(stale_owner), encoding="utf-8")
    original_open = runtime.os.open
    contender_fd: int | None = None
    contender_reads = 0

    def contender_wins(path: str | Path, flags: int, mode: int = 0o777) -> int:
        nonlocal contender_fd, contender_reads
        if Path(path) == lock_path and flags == (runtime.os.O_RDWR | runtime.os.O_CREAT | runtime.os.O_EXCL) and not lock_path.exists():
            contender_fd = original_open(path, flags, mode)
        elif Path(path) == lock_path and flags == runtime.os.O_RDONLY and contender_fd is not None:
            contender_reads += 1
            if contender_reads == 2:
                runtime.os.write(contender_fd, json.dumps(contender_owner).encode("utf-8"))
                runtime.fcntl.flock(contender_fd, runtime.fcntl.LOCK_EX)
        return original_open(path, flags, mode)

    monkeypatch.setattr(runtime.os, "open", contender_wins)
    try:
        lock_fd, payload = runtime.acquire_lock(root, stale_after=1)
    finally:
        if contender_fd is not None:
            runtime.fcntl.flock(contender_fd, runtime.fcntl.LOCK_UN)
            runtime.os.close(contender_fd)

    assert lock_fd is None
    assert contender_reads == 2
    assert payload == contender_owner
    assert not list(root.glob("heartbeat.lock.recovered-*"))
    assert json.loads(lock_path.read_text(encoding="utf-8")) == contender_owner


def test_heartbeat_pre_run_failure_is_not_masked_by_cleanup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = load_runtime()
    target = tmp_path / "repo"
    target.mkdir()
    write_config(target)

    def fail_run_id() -> str:
        raise runtime.HeartbeatError("run identifier failure")

    monkeypatch.setattr(runtime, "_new_run_id", fail_run_id)
    with pytest.raises(runtime.HeartbeatError, match="run identifier failure"):
        runtime.run_once(target_root=target, no_agent=True)


def test_heartbeat_locked_run_does_not_recover_active_state(tmp_path: Path) -> None:
    runtime = load_runtime()
    target = tmp_path / "repo"
    target.mkdir()
    write_config(target)
    root = state_root(target)
    staged = root / "runs" / "active.staged"
    staged.mkdir(parents=True)
    active = root / "active.json"
    active.write_text(json.dumps({"path": "runs/active.staged"}), encoding="utf-8")
    active_before = active.read_text(encoding="utf-8")
    lock_fd, _ = runtime.acquire_lock(root, stale_after=1)
    assert lock_fd is not None
    try:
        payload = runtime.run_once(target_root=target, no_agent=True)
    finally:
        runtime.release_lock(root, lock_fd)

    assert payload["status"] == "locked"
    assert staged.is_dir()
    assert active.read_text(encoding="utf-8") == active_before


def test_heartbeat_manifest_commits_and_validates_each_sidecar(tmp_path: Path) -> None:
    runtime = load_runtime()
    target = tmp_path / "repo"
    target.mkdir()
    write_config(
        target,
        hooks={
            "before": [{"id": "sidecar", "command": [sys.executable, "-c", "print('ok')"], "timeout_seconds": 5}],
            "after": [],
        },
    )

    payload = runtime.run_once(target_root=target, no_agent=True)

    assert payload["ok"] is True
    run_dir = state_root(target) / payload["latest"]["path"]
    entry = json.loads((run_dir / "command-log.json").read_text(encoding="utf-8"))["commands"][0]
    assert payload["manifest"]["artifacts"][entry["sidecar"]] == entry["sidecar_sha256"]
    (run_dir / entry["sidecar"]).write_text("{}\n", encoding="utf-8")
    with pytest.raises(runtime.HeartbeatError, match="artifact hash mismatch"):
        runtime.validate_staged_run(run_dir)


@pytest.mark.parametrize(
    ("command", "error"),
    [
        (["git", "-C", ".", "push"], "git push"),
        (["git", "--git-dir=.", "commit"], "git commit"),
    ],
)
def test_heartbeat_direct_command_policy_blocks_git_global_option_bypasses(
    tmp_path: Path, command: list[str], error: str
) -> None:
    runtime = load_runtime()
    target = tmp_path / "repo"
    target.mkdir()
    write_config(target, hooks={"before": [{"id": "blocked", "command": command, "allow_direct": True}], "after": []})

    payload = runtime.run_once(target_root=target, no_agent=True)

    assert payload["ok"] is False
    run_dir = state_root(target) / payload["latest"]["path"]
    entry = json.loads((run_dir / "command-log.json").read_text(encoding="utf-8"))["commands"][0]
    assert entry["blocked"] is True
    assert error in entry["error"]
    assert entry["sidecar"] in payload["manifest"]["artifacts"]
    assert entry["cwd"] == str(target)
    assert entry["timeout_seconds"] > 0
    assert entry["started_at"] <= entry["finished_at"]
    assert entry["returncode"] is None
    assert entry["timed_out"] is False
    assert entry["stdout_tail"] == ""
    assert entry["stderr_tail"] == ""
