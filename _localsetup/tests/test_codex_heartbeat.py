import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from _localsetup.core.apply import apply_plan
from _localsetup.core.harness import HEARTBEAT_TASK_ID
from _localsetup.core.harness import budget as harness_budget
from _localsetup.core.harness import disable as harness_disable
from _localsetup.core.harness import enable as harness_enable
from _localsetup.core.harness import init as harness_init
from _localsetup.core.harness import plan as harness_plan
from _localsetup.core.harness import run as harness_run
from _localsetup.core.harness import status as harness_status
from _localsetup.core.plan import build_install_plan
from _localsetup.core.skills import selected_skill_names
from _localsetup.core.workflows import selected_workflow_names


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "_localsetup" / "skills" / "ls-codex-heartbeat" / "scripts" / "codex_heartbeat.py"


def load_runtime():
    spec = importlib.util.spec_from_file_location("codex_heartbeat_test_runtime", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_config(
    target: Path,
    *,
    enabled: bool = True,
    task_queue_path: str | None = None,
    hooks: dict | None = None,
    codex: dict | None = None,
    agent_profiles: dict | None = None,
) -> Path:
    config = {
        "heartbeat": {
            "enabled": enabled,
            "interval_minutes": 15,
            "state_dir": ".localsetup/state/codex-heartbeat",
            "task_queue_path": task_queue_path,
        },
        "codex": {"enabled": False, "command": ["codex", "exec", "--", "status"]},
        "hooks": hooks or {"before": [], "after": []},
        "direct_command_policy": {
            "allow_git_writes": False,
            "allow_destructive": False,
            "allowlist": [],
        },
    }
    if codex is not None:
        config["codex"] = codex
    if agent_profiles is not None:
        config["agent_profiles"] = agent_profiles
    path = target / "config" / "codex_heartbeat.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def state_root(target: Path) -> Path:
    return target / ".localsetup" / "state" / "codex-heartbeat"


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


def test_harness_pack_selects_heartbeat_skill_and_workflow() -> None:
    assert "ls-codex-heartbeat" in selected_skill_names(ROOT, ["harness"])
    assert "ls-cron-orchestrator" in selected_skill_names(ROOT, ["harness"])
    assert "ls-workflow-codex-heartbeat" in selected_workflow_names(ROOT, ["harness"])
    assert "ls-workflow-repo-finalizer" in selected_workflow_names(ROOT, ["harness"])


def test_normal_install_of_harness_pack_does_not_activate_target(tmp_path: Path) -> None:
    target = tmp_path / "target"
    home = tmp_path / "home"
    target.mkdir()
    plan = build_install_plan(ROOT, home=home, packs=["harness"], target_root=target)
    result = apply_plan(ROOT, plan, home=home, target_root=target)

    assert result["dry_run"] is False
    assert (home / ".local/share/localsetup/packages/ls-codex-heartbeat").is_dir()
    assert not (target / "HEARTBEAT.md").exists()
    assert not (target / "config" / "codex_heartbeat.yaml").exists()
    assert not (target / "cron" / "manifest.yaml").exists()
    assert not (target / ".localsetup" / "state" / "codex-heartbeat").exists()


def test_harness_init_enable_run_status_disable_are_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()

    first_init = harness_init(ROOT, target)
    second_init = harness_init(ROOT, target)
    enable_one = harness_enable(ROOT, target)
    enable_two = harness_enable(ROOT, target)
    run_payload = harness_run(ROOT, target, no_agent=True)
    status_payload = harness_status(ROOT, target)
    disable_one = harness_disable(ROOT, target)
    disable_two = harness_disable(ROOT, target)

    assert first_init["created"]["HEARTBEAT.md"] is True
    assert second_init["created"]["HEARTBEAT.md"] is False
    assert enable_one["enabled"] is True
    assert enable_two["enabled"] is True
    assert run_payload["ok"] is True
    assert status_payload["latest"]["status"] == "succeeded"
    assert disable_one["enabled"] is False
    assert disable_two["enabled"] is False
    config = yaml.safe_load((target / "config" / "codex_heartbeat.yaml").read_text(encoding="utf-8"))
    assert config["heartbeat"]["enabled"] is False
    manifest = yaml.safe_load((target / "cron" / "manifest.yaml").read_text(encoding="utf-8"))
    task = next(task for task in manifest["tasks"] if task["id"] == HEARTBEAT_TASK_ID)
    assert task["enabled"] is False


def test_harness_cron_upsert_preserves_unrelated_entries_and_validates(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    manifest = target / "cron" / "manifest.yaml"
    manifest.parent.mkdir()
    manifest.write_text(
        yaml.safe_dump(
            {
                "triggers": {"nightly": {"schedule": "0 2 * * *"}},
                "tasks": [
                    {
                        "id": "keep",
                        "trigger": "nightly",
                        "sequence_order": 1,
                        "command": [sys.executable, "-c", "print('keep')"],
                        "enabled": True,
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    harness_enable(ROOT, target)

    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    assert "nightly" in data["triggers"]
    assert "codex-heartbeat" in data["triggers"]
    assert any(task["id"] == "keep" for task in data["tasks"])
    assert any(task["id"] == HEARTBEAT_TASK_ID for task in data["tasks"])
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "_localsetup" / "skills" / "ls-cron-orchestrator" / "scripts" / "cron_ctl.py"),
            "--manifest",
            str(manifest),
            "validate",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_harness_live_crontab_requires_yes(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()

    with pytest.raises(RuntimeError, match="requires --install-crontab and --yes"):
        harness_enable(ROOT, target, install_crontab=True, yes=False)
    assert not (target / "config" / "codex_heartbeat.yaml").exists()
    assert not (target / "cron" / "manifest.yaml").exists()


def test_harness_plan_reports_launcher_from_source_checkout(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()

    payload = harness_plan(ROOT, target)

    command = payload["launcher_command"]
    assert command[0].endswith("localsetup") or str(ROOT / "_localsetup" / "tools" / "localsetup.py") in command
    assert "_localsetup/skills/ls-codex-heartbeat" not in " ".join(command)


def test_harness_budget_missing_queue_uses_safe_defaults(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()

    payload = harness_budget(ROOT, target)

    assert payload["ok"] is True
    assert payload["policy"]["effective_runtime_seconds"] == 720
    assert payload["policy"]["max_parallel"] == 1
    assert payload["policy"]["max_total"] == 1
    assert payload["policy"]["max_depth"] == 1
    assert payload["policy"]["execution_order"] == "serial"
    assert payload["policy"]["allow_git_writes"] is False
    assert payload["policy"]["allow_destructive"] is False
    assert payload["summary"]["task_count"] == 0
    assert payload["tasks"] == []


def test_harness_budget_caps_runtime_from_interval_and_queue_policy(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    write_config(target, task_queue_path="queues/heartbeat-tasks.yaml")
    queue = target / "queues" / "heartbeat-tasks.yaml"
    queue.parent.mkdir()
    queue.write_text(
        yaml.safe_dump(
            {
                "policy": {
                    "max_subagent_occupancy_ratio": 0.5,
                    "max_parallel": 2,
                    "max_total": 3,
                    "max_depth": 2,
                },
                "tasks": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    payload = harness_budget(ROOT, target)

    assert payload["policy"]["effective_runtime_seconds"] == 450
    assert payload["policy"]["max_parallel"] == 2
    assert payload["policy"]["max_total"] == 3
    assert payload["policy"]["max_depth"] == 2


def test_harness_budget_serial_carryover_uses_actual_for_completed(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    write_config(target, task_queue_path="queues/heartbeat-tasks.yaml", codex={"enabled": False, "timeout_seconds": 120})
    queue = target / "queues" / "heartbeat-tasks.yaml"
    queue.parent.mkdir()
    queue.write_text(
        yaml.safe_dump(
            {
                "tasks": [
                    {"id": "done", "status": "completed", "allocated_runtime_seconds": 300, "actual_runtime_seconds": 45},
                    {"id": "pending", "status": "planned", "allocated_runtime_seconds": 300},
                    {"id": "unknown-time", "status": "assigned"},
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    payload = harness_budget(ROOT, target)

    assert payload["tasks"][0]["reserved_runtime_seconds"] == 45
    assert payload["tasks"][0]["reservation_rule"] == "actual"
    assert payload["tasks"][1]["reserved_runtime_seconds"] == 300
    assert payload["tasks"][2]["reserved_runtime_seconds"] == 120
    assert payload["summary"]["reserved_runtime_seconds"] == 465


def test_harness_budget_clamps_hostile_numeric_values(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    write_config(
        target,
        task_queue_path="queues/heartbeat-tasks.yaml",
        codex={"enabled": False, "profile": "heartbeat"},
        agent_profiles={"heartbeat": {"timeout_seconds": -5}},
    )
    queue = target / "queues" / "heartbeat-tasks.yaml"
    queue.parent.mkdir()
    queue.write_text(
        yaml.safe_dump(
            {
                "policy": {
                    "max_subagent_occupancy_ratio": 2,
                    "max_parallel": 0,
                    "max_total": -3,
                    "max_depth": 0,
                },
                "tasks": [
                    {"id": "bad-allocation", "status": "planned", "allocated_runtime_seconds": -1},
                    {"id": "bad-timeout", "status": "planned", "timeout_seconds": -5},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    payload = harness_budget(ROOT, target)

    assert payload["policy"]["max_subagent_occupancy_ratio"] == 1.0
    assert payload["policy"]["max_parallel"] == 1
    assert payload["policy"]["max_total"] == 1
    assert payload["policy"]["max_depth"] == 1
    assert payload["policy"]["default_timeout_seconds"] == 1800
    assert all(task["reserved_runtime_seconds"] > 0 for task in payload["tasks"])
    assert payload["summary"]["remaining_runtime_seconds"] <= payload["policy"]["effective_runtime_seconds"]


def test_harness_budget_defaults_non_finite_occupancy_ratio(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    write_config(target, task_queue_path="queues/heartbeat-tasks.yaml")
    queue = target / "queues" / "heartbeat-tasks.yaml"
    queue.parent.mkdir()
    queue.write_text(
        "policy:\n"
        "  max_subagent_occupancy_ratio: .nan\n"
        "tasks:\n"
        "  - id: one\n"
        "    status: planned\n"
        "    allocated_runtime_seconds: -1\n",
        encoding="utf-8",
    )

    nan_payload = harness_budget(ROOT, target)
    assert nan_payload["policy"]["max_subagent_occupancy_ratio"] == 0.8
    assert nan_payload["policy"]["effective_runtime_seconds"] == 720

    queue.write_text(
        "policy:\n"
        "  max_subagent_occupancy_ratio: .inf\n"
        "tasks: []\n",
        encoding="utf-8",
    )
    inf_payload = harness_budget(ROOT, target)
    assert inf_payload["policy"]["max_subagent_occupancy_ratio"] == 0.8
    assert inf_payload["policy"]["effective_runtime_seconds"] == 720


def test_harness_budget_defaults_non_finite_integer_fields(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    write_config(target, task_queue_path="queues/heartbeat-tasks.yaml")
    queue = target / "queues" / "heartbeat-tasks.yaml"
    queue.parent.mkdir()
    queue.write_text(
        "policy:\n"
        "  max_parallel: .inf\n"
        "  max_total: .nan\n"
        "  max_depth: -.inf\n"
        "tasks:\n"
        "  - id: one\n"
        "    status: planned\n"
        "    allocated_runtime_seconds: .inf\n"
        "  - id: two\n"
        "    status: planned\n"
        "    timeout_seconds: .nan\n",
        encoding="utf-8",
    )

    payload = harness_budget(ROOT, target)

    assert payload["ok"] is True
    assert payload["policy"]["max_parallel"] == 1
    assert payload["policy"]["max_total"] == 1
    assert payload["policy"]["max_depth"] == 1
    assert [task["reserved_runtime_seconds"] for task in payload["tasks"]] == [1800, 1800]


def test_harness_budget_rejects_queue_path_outside_target(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    outside = tmp_path / "outside" / "queue.yaml"
    outside.parent.mkdir()
    outside.write_text("tasks: []\n", encoding="utf-8")
    write_config(target, task_queue_path="../outside/queue.yaml")

    traversal_payload = harness_budget(ROOT, target)
    assert traversal_payload["ok"] is False
    assert traversal_payload["summary"]["task_queue_exists"] is False
    assert "under target_root" in traversal_payload["summary"]["queue_error"]

    config = yaml.safe_load((target / "config" / "codex_heartbeat.yaml").read_text(encoding="utf-8"))
    config["heartbeat"]["task_queue_path"] = str(outside)
    (target / "config" / "codex_heartbeat.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    absolute_payload = harness_budget(ROOT, target)
    assert absolute_payload["ok"] is False
    assert "repo-local" in absolute_payload["summary"]["queue_error"]


def test_harness_budget_cli_dispatch(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "_localsetup" / "tools" / "localsetup.py"),
            "--source-root",
            str(ROOT),
            "--target-directory",
            str(target),
            "harness",
            "codex-heartbeat",
            "budget",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["summary"]["task_count"] == 0
