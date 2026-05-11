import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from _localsetup.v3.apply import apply_plan
from _localsetup.v3.boundary import scan_tar_for_leaks
from _localsetup.v3.cli import _split_csv
from _localsetup.v3.config import InstallConfig, load_install_config, merge_cli_config
from _localsetup.v3.context import build_agent_context, render_markdown_report
from _localsetup.v3.conversion import convert_repo
from _localsetup.v3.dependencies import ensure_dependencies, missing_requirements
from _localsetup.v3.doctor import run_doctor
from _localsetup.v3.docs import generate_alias_outputs
from _localsetup.v3.hooks import run_maintainer_gate
from _localsetup.v3.lockfile import load_json
from _localsetup.v3.migration import conservative_migrate, detect_legacy_artifacts, scan_legacy_references
from _localsetup.v3.package import build_public_artifact
from _localsetup.v3.plan import build_install_plan
from _localsetup.v3.rollback import rollback
from _localsetup.v3.shell import detect_invocation_target, is_managed_shim, register_shell_command, shell_registration_status
from _localsetup.v3.verify import verify_install
from _localsetup.v3.workflows import workflow_catalog_payload


def make_temp_repo(tmp_path: Path) -> Path:
    source = Path(__file__).resolve().parents[2]
    repo = tmp_path / "repo"
    (repo / "_localsetup").mkdir(parents=True)
    shutil.copytree(source / "_localsetup" / "config", repo / "_localsetup" / "config")
    shutil.copytree(source / "_localsetup" / "v3", repo / "_localsetup" / "v3")
    shutil.copytree(source / "_localsetup" / "skills", repo / "_localsetup" / "skills")
    shutil.copytree(source / "_localsetup" / "workflows", repo / "_localsetup" / "workflows")
    shutil.copytree(source / "_localsetup" / "tools", repo / "_localsetup" / "tools")
    shutil.copy2(source / "_localsetup" / "requirements.txt", repo / "_localsetup" / "requirements.txt")
    shutil.copy2(source / "VERSION", repo / "VERSION")
    (repo / "_localsetup" / "docs" / "_generated").mkdir(parents=True)
    (repo / "_localsetup" / "docs" / "migration").mkdir(parents=True)
    for rel_path in ("README.md", "FEATURES.md", "PLATFORM_REGISTRY.md"):
        shutil.copy2(source / "_localsetup" / "docs" / rel_path, repo / "_localsetup" / "docs" / rel_path)
    (repo / ".github").mkdir()
    (repo / "README.md").write_text("# Localsetup\n", encoding="utf-8")
    (repo / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
    return repo


def test_v3_plan_apply_verify_rollback(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)

    plan = build_install_plan(root, home=home, packs=["core"])
    assert not any(a.kind == "attach_repo_path" for a in plan.actions)
    assert plan.rollback_metadata["platforms"] == []
    assert plan.rollback_metadata["global_only"] is True

    result = apply_plan(root, plan, home=home, dry_run=False)
    assert result["dry_run"] is False

    verify = verify_install(root, home)
    assert verify["ok"] is True
    assert (home / ".local/share/agents/skills/localsetup/ls-context").is_dir()
    assert not (home / ".local/share/agents/skills/localsetup/ls-cloudflare-dns").exists()
    assert verify["adapters"] == []
    lock = load_json(root / "localsetup.lock.json")
    assert lock["platforms"] == []
    assert lock["adapter_state"] == []
    for rel in (".codex/skills", ".claude/skills", ".cursor/skills", ".kilo/skills", ".opencode/skills", ".openclaw/skills"):
        assert not (root / rel).exists()

    rolled = rollback(root, home)
    assert rolled["removed"]
    assert verify_install(root, home)["ok"] is False


def test_v3_selected_workflows_install_as_skill_packages(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)

    plan = build_install_plan(root, home=home, packs=["ops"], platform_ids=["codex"])
    workflow_action = next(a for a in plan.actions if a.kind == "install_workflows")
    assert "ls-workflow-ops-tmux-session" in workflow_action.details["workflows"]
    assert "ls-workflow-pipeline-server-triage-patch" in workflow_action.details["workflows"]
    assert "ls-linux-patcher" in plan.rollback_metadata["skills"]

    result = apply_plan(root, plan, home=home, dry_run=False)
    lock = load_json(root / "localsetup.lock.json")
    global_root = home / ".local/share/agents/skills/localsetup"

    assert result["dry_run"] is False
    assert (global_root / "ls-workflow-ops-tmux-session" / "SKILL.md").is_file()
    assert (global_root / "ls-workflow-ops-tmux-session" / "workflow.yaml").is_file()
    assert "ls-workflow-ops-tmux-session" in lock["workflows"]
    assert any(path.endswith("ls-workflow-ops-tmux-session") for path in lock["installed_workflows"])
    assert verify_install(root, home, platform_ids=["codex"])["ok"] is True


def test_v3_portable_mode_uses_managed_copies(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)

    plan = build_install_plan(root, home=home, packs=["core"], attach_mode="portable", platform_ids=["codex"])
    result = apply_plan(root, plan, home=home, dry_run=False)

    assert result["dry_run"] is False
    verify = verify_install(root, home, platform_ids=["codex"])
    assert verify["ok"] is True
    assert all(adapter["is_portable_copy"] for adapter in verify["adapters"])
    assert not (root / ".cursor" / "skills").exists()

    rolled = rollback(root, home)
    assert rolled["removed"]


def test_v3_platform_selector_limits_adapters(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)

    plan = build_install_plan(root, home=home, packs=["core"], platform_ids=["codex"])
    result = apply_plan(root, plan, home=home, dry_run=False)

    assert result["dry_run"] is False
    assert (root / ".codex" / "skills").is_symlink()
    assert not (root / ".kilo" / "skills").exists()
    assert not (root / ".cursor" / "skills").exists()
    verify = verify_install(root, home, platform_ids=["codex"])
    assert verify["ok"] is True
    assert {adapter["platform"] for adapter in verify["adapters"]} == {"codex"}

    with pytest.raises(ValueError, match="platform-scoped rollback"):
        rollback(root, home, platform_ids=["codex"])


def test_v3_multi_platform_selector_attaches_only_requested_adapters(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)

    plan = build_install_plan(root, home=home, packs=["core"], platform_ids=["codex", "kilo"])
    result = apply_plan(root, plan, home=home, dry_run=False)
    verify = verify_install(root, home)

    assert result["dry_run"] is False
    assert {Path(adapter["repo_path"]).parent.name for adapter in verify["adapters"]} == {".codex", ".kilo"}
    assert {adapter["platform"] for adapter in verify["adapters"]} == {"codex", "kilo"}
    assert (root / ".codex" / "skills").is_symlink()
    assert (root / ".kilo" / "skills").is_symlink()
    assert not (root / ".cursor" / "skills").exists()


def test_v3_external_target_directory_attaches_selected_adapter(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "other-repo"
    target.mkdir()
    (target / "README.md").write_text("# Other repo\n", encoding="utf-8")

    plan = build_install_plan(root, home=home, packs=["core"], platform_ids=["cursor"], target_root=target)
    result = apply_plan(root, plan, home=home)
    verify = verify_install(root, home, target_root=target)
    lock = load_json(target / "localsetup.lock.json")

    assert result["dry_run"] is False
    assert (target / ".cursor" / "skills").is_symlink()
    assert not (root / ".cursor" / "skills").exists()
    assert verify["ok"] is True
    assert {adapter["platform"] for adapter in verify["adapters"]} == {"cursor"}
    assert lock["target_root"] == str(target)
    assert lock["platforms"] == ["cursor"]
    assert not (root / "localsetup.lock.json").exists()


def test_detect_invocation_target_prefers_git_root(tmp_path: Path) -> None:
    project = tmp_path / "project"
    nested = project / "a" / "b"
    nested.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=project, text=True, capture_output=True, check=True)

    assert detect_invocation_target(nested) == project.resolve()

    outside = tmp_path / "outside"
    outside.mkdir()
    assert detect_invocation_target(outside) == outside.resolve()


def test_shell_registration_writes_managed_idempotent_shim_and_blocks_collision(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"

    first = register_shell_command(root, home=home, path_env="")
    second = register_shell_command(root, home=home, path_env=str(home / ".local" / "bin"))
    shim = home / ".local" / "bin" / "localsetup"

    assert first["managed"] is True
    assert first["path"]["on_path"] is False
    assert second["path"]["on_path"] is True
    assert is_managed_shim(shim)
    assert shell_registration_status(root, home=home, path_env="")["source_root"] == str(root.resolve())

    shim.write_text("#!/usr/bin/env bash\necho unmanaged\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unmanaged localsetup"):
        register_shell_command(root, home=home)


def test_shell_registration_warns_when_path_precedence_hides_shim(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    earlier = tmp_path / "earlier"
    earlier.mkdir()
    fake = earlier / "localsetup"
    fake.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake.chmod(0o755)

    result = register_shell_command(root, home=home, path_env=f"{earlier}:{home / '.local' / 'bin'}")

    assert result["path"]["on_path"] is True
    assert result["which"] == str(fake)
    assert any("before the managed shim" in warning for warning in result["warnings"])


def test_custom_home_shim_invocation_uses_registered_home(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "custom-home"
    target = tmp_path / "target"
    target.mkdir()
    register_shell_command(root, home=home, path_env=str(home / ".local" / "bin"))

    completed = subprocess.run(
        [
            str(home / ".local" / "bin" / "localsetup"),
            "--target-directory",
            str(target),
            "install",
            "--yes",
            "--dependency-mode",
            "prompt-only",
            "--tools",
            "codex",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert (home / ".local/share/agents/skills/localsetup/ls-context").is_dir()
    assert (target / ".codex" / "skills").is_symlink()


def test_v3_cli_tools_and_yes_aliases_install(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    tool = root / "_localsetup" / "tools" / "localsetup_v3.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(tool),
            "--repo",
            str(root),
            "--home",
            str(home),
            "install",
            "--yes",
            "--dependency-mode",
            "prompt-only",
            "--tools",
            "codex",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["attachment"]["platforms"] == ["codex"]
    assert (root / ".codex" / "skills").is_symlink()


def test_global_shim_invocation_installs_at_detected_git_root(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target"
    nested = target / "nested" / "deeper"
    nested.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=target, text=True, capture_output=True, check=True)
    tool = root / "_localsetup" / "tools" / "localsetup_v3.py"
    env = {**os.environ, "LOCALSETUP_GLOBAL_SHIM": "1"}

    completed = subprocess.run(
        [
            sys.executable,
            str(tool),
            "--repo",
            str(root),
            "--home",
            str(home),
            "install",
            "--yes",
            "--dependency-mode",
            "prompt-only",
            "--tools",
            "codex",
        ],
        cwd=nested,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["attachment"]["target_root"] == str(target.resolve())
    assert (target / ".codex" / "skills").is_symlink()
    assert (target / "localsetup.lock.json").is_file()
    assert not (root / ".codex" / "skills").exists()


def test_v3_apply_rejects_target_root_that_differs_from_plan(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target-repo"
    other = tmp_path / "other-target"
    target.mkdir()
    other.mkdir()

    plan = build_install_plan(root, home=home, packs=["core"], platform_ids=["cursor"], target_root=target)

    with pytest.raises(ValueError, match="target_root does not match install plan target_root"):
        apply_plan(root, plan, home=home, target_root=other)


def test_v3_legacy_detection_uses_external_target_lockfile(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target-repo"
    target.mkdir()
    (root / "localsetup.lock.json").write_text('{"source": true}\n', encoding="utf-8")
    (target / "localsetup.lock.json").write_text('{"target": true}\n', encoding="utf-8")

    artifacts = detect_legacy_artifacts(root, home=home, target_root=target)
    lock_paths = [Path(item["path"]) for item in artifacts if item["kind"] == "lockfile"]

    assert lock_paths == [target / "localsetup.lock.json"]


def test_v3_target_directory_without_selector_is_global_only(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "other-repo"
    target.mkdir()

    plan = build_install_plan(root, home=home, packs=["core"], target_root=target)
    result = apply_plan(root, plan, home=home, target_root=target)
    verify = verify_install(root, home, target_root=target)
    doctor = run_doctor(root, home=home, platform_ids=None, target_root=target)
    lock = load_json(target / "localsetup.lock.json")

    assert result["dry_run"] is False
    assert verify["ok"] is True
    assert verify["adapters"] == []
    assert lock["platforms"] == []
    assert lock["adapter_state"] == []
    assert not (target / ".cursor" / "skills").exists()
    assert any("no platforms were selected" in warning for warning in doctor["warnings"])


def test_v3_preserves_existing_platform_config_when_attaching_skills(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    rules = root / ".cursor" / "rules"
    rules.mkdir(parents=True)
    (rules / "project.mdc").write_text("keep me\n", encoding="utf-8")

    plan = build_install_plan(root, home=home, packs=["core"], platform_ids=["cursor"])
    apply_plan(root, plan, home=home)

    assert (root / ".cursor" / "skills").is_symlink()
    assert (rules / "project.mdc").read_text(encoding="utf-8") == "keep me\n"


@pytest.mark.parametrize("collision_kind", ["directory", "file", "wrong_symlink", "dangling_symlink"])
def test_v3_refuses_unmanaged_adapter_collisions(tmp_path: Path, collision_kind: str) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    adapter = root / ".cursor" / "skills"
    adapter.parent.mkdir(parents=True)
    if collision_kind == "directory":
        adapter.mkdir()
        (adapter / "custom.txt").write_text("user content\n", encoding="utf-8")
        expected = "unmanaged adapter directory"
    elif collision_kind == "file":
        adapter.write_text("not a directory\n", encoding="utf-8")
        expected = "regular file"
    elif collision_kind == "wrong_symlink":
        wrong_target = tmp_path / "wrong-target"
        wrong_target.mkdir()
        adapter.symlink_to(wrong_target)
        expected = "symlink points outside managed library"
    else:
        adapter.symlink_to(tmp_path / "missing-target")
        expected = "dangling symlink"

    plan = build_install_plan(root, home=home, packs=["core"], platform_ids=["cursor"])

    with pytest.raises(RuntimeError, match=expected):
        apply_plan(root, plan, home=home)


def test_v3_rerun_with_correct_managed_symlink_is_idempotent(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"

    plan = build_install_plan(root, home=home, packs=["core"], platform_ids=["codex"])
    first = apply_plan(root, plan, home=home)
    second = apply_plan(root, plan, home=home)
    verify = verify_install(root, home)

    assert first["dry_run"] is False
    assert second["dry_run"] is False
    assert verify["ok"] is True
    assert (root / ".codex" / "skills").is_symlink()


def test_v3_doctor_reports_selected_adapter_collisions_only(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    collision = root / ".cursor" / "skills"
    collision.mkdir(parents=True)

    global_only = run_doctor(root, home=home)
    selected = run_doctor(root, home=home, platform_ids=["cursor"])

    assert global_only["adapter_collisions"] == []
    assert not any("adapter collision" in blocker for blocker in global_only["blockers"])
    assert selected["ok"] is False
    assert selected["adapter_collisions"][0]["reason"] == "unmanaged adapter directory"


def test_cli_rejects_empty_csv_selectors() -> None:
    with pytest.raises(ValueError, match="empty value"):
        _split_csv([","])
    with pytest.raises(ValueError, match="empty value"):
        _split_csv(["codex,"])
    with pytest.raises(ValueError, match="empty value"):
        _split_csv([" "])


def test_v3_rejects_unknown_platform_selectors(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)

    with pytest.raises(ValueError, match="unknown platform selector"):
        build_install_plan(root, home=home, packs=["core"], platform_ids=["typo"])
    with pytest.raises(ValueError, match="unknown platform selector"):
        verify_install(root, home, platform_ids=["typo"])
    with pytest.raises(ValueError, match="unknown platform selector"):
        rollback(root, home, platform_ids=["typo"])


def test_v3_cli_csv_selector_normalization() -> None:
    assert _split_csv(["codex,kilo", "cursor"]) == ["codex", "kilo", "cursor"]
    assert _split_csv(None) is None


def test_v3_config_file_and_cli_precedence(tmp_path: Path) -> None:
    config_path = tmp_path / "install.json"
    config_path.write_text(
        """{
  "platforms": ["codex"],
  "packs": ["dev"],
  "attach_mode": "portable",
  "target_directory": "/tmp/localsetup-target",
  "dependency_mode": "prompt-only",
  "migration_mode": "report-only",
  "output": {"json": true}
}
""",
        encoding="utf-8",
    )

    base = load_install_config(config_path)
    merged = merge_cli_config(base, packs=["core"], attach_mode="symlink", dependency_mode="managed-venv")

    assert base.platforms == ["codex"]
    assert base.packs == ["dev"]
    assert base.attach_mode == "portable"
    assert base.target_directory == "/tmp/localsetup-target"
    assert merged.packs == ["core"]
    assert merged.attach_mode == "symlink"
    assert merged.target_directory == "/tmp/localsetup-target"
    assert merged.dependency_mode == "managed-venv"


def test_v3_managed_venv_commands_and_lock_interpreter(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    commands: list[list[str]] = []

    def fake_runner(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        commands.append(cmd)
        if cmd[1:3] == ["-m", "venv"]:
            python_path = Path(cmd[3]) / "bin" / "python"
            python_path.parent.mkdir(parents=True, exist_ok=True)
            python_path.write_text("# fake python\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    deps = ensure_dependencies(root, mode="managed-venv", runner=fake_runner)
    plan = build_install_plan(root, home=home, packs=["core"], platform_ids=["codex"])
    result = apply_plan(root, plan, home=home, dependency_info=deps)
    lock = load_json(root / "localsetup.lock.json")

    assert any(cmd[1:3] == ["-m", "venv"] for cmd in commands)
    assert any(cmd[2:4] == ["pip", "install"] and "-r" in cmd for cmd in commands)
    assert any(cmd[-2:] == ["pip", "check"] for cmd in commands)
    assert deps["interpreter"].endswith(".localsetup/venv/bin/python")
    assert lock["python_interpreter"] == deps["interpreter"]
    assert result["lockfile"].endswith("localsetup.lock.json")


def test_v3_missing_requirements_checks_selected_interpreter(tmp_path: Path) -> None:
    req = tmp_path / "requirements.txt"
    req.write_text("PGPy>=0.6.0\nDefinitely-Missing-Package>=1\n", encoding="utf-8")

    def fake_runner(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        assert cmd[:2] == ["/tmp/venv/bin/python", "-c"]
        return subprocess.CompletedProcess(cmd, 0, stdout='["PGPy"]\n', stderr="")

    assert missing_requirements(req, python="/tmp/venv/bin/python", runner=fake_runner) == [
        "Definitely-Missing-Package"
    ]


def test_v3_missing_requirements_probe_failure_does_not_fall_back(tmp_path: Path) -> None:
    req = tmp_path / "requirements.txt"
    req.write_text("pytest>=1\n", encoding="utf-8")

    def fake_runner(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="probe failed")

    assert missing_requirements(req, python="/tmp/venv/bin/python", runner=fake_runner) == ["pytest"]


def test_skill_smoke_runner_uses_current_python_without_shell(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    script = Path(__file__).resolve().parents[2] / "_localsetup/skills/ls-skill-sandbox-tester/scripts/run_smoke.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--sandbox-dir",
            str(sandbox),
            "--command",
            "python -c 'import sys; print(sys.executable)'",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == sys.executable


def test_v3_agent_context_and_markdown_report(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    config = InstallConfig(platforms=["codex"], packs=["core"], dependency_mode="prompt-only")

    context = build_agent_context(root, home=home, config=config)
    markdown = render_markdown_report(context)

    assert {"environment", "selected_platforms", "dependencies", "migration", "actions", "blockers", "warnings", "commands", "rollback", "verification"} <= set(context)
    assert context["selected_platforms"] == ["codex"]
    assert context["selected_packs"] == ["core"]
    assert "# Localsetup v3 Install Context" in markdown
    assert "python3 _localsetup/tools/localsetup_v3.py verify --platforms codex" in markdown


def test_v3_cli_doctor_target_warning_requires_explicit_target(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target-repo"
    target.mkdir()
    tool = root / "_localsetup" / "tools" / "localsetup_v3.py"

    plain = subprocess.run(
        [
            sys.executable,
            str(tool),
            "--repo",
            str(root),
            "--home",
            str(home),
            "doctor",
            "--dependency-mode",
            "prompt-only",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    explicit = subprocess.run(
        [
            sys.executable,
            str(tool),
            "--repo",
            str(root),
            "--home",
            str(home),
            "--target-directory",
            str(target),
            "doctor",
            "--dependency-mode",
            "prompt-only",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    plain_payload = json.loads(plain.stdout)
    explicit_payload = json.loads(explicit.stdout)
    assert not any("target directory was provided" in warning for warning in plain_payload["warnings"])
    assert any("target directory was provided" in warning for warning in explicit_payload["warnings"])


def test_v3_cli_context_target_warning_requires_explicit_target(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target-repo"
    target.mkdir()
    tool = root / "_localsetup" / "tools" / "localsetup_v3.py"

    plain = subprocess.run(
        [
            sys.executable,
            str(tool),
            "--repo",
            str(root),
            "--home",
            str(home),
            "context",
            "--dependency-mode",
            "prompt-only",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    explicit = subprocess.run(
        [
            sys.executable,
            str(tool),
            "--repo",
            str(root),
            "--home",
            str(home),
            "--target-directory",
            str(target),
            "context",
            "--dependency-mode",
            "prompt-only",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    plain_payload = json.loads(plain.stdout)
    explicit_payload = json.loads(explicit.stdout)
    assert not any("target directory was provided" in warning for warning in plain_payload["warnings"])
    assert any("target directory was provided" in warning for warning in explicit_payload["warnings"])


def test_docs_do_not_show_selector_free_portable_install() -> None:
    root = Path(__file__).resolve().parents[2]
    overview = (root / "_localsetup" / "docs" / "migration" / "v3-overview.md").read_text(encoding="utf-8")

    assert "install --mode portable --apply" not in overview
    assert "install --mode portable --platforms codex --apply" in overview


def test_v3_docs_and_package(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    (root / "_localsetup" / "__pycache__").mkdir()
    (root / "_localsetup" / "__pycache__" / "cached.pyc").write_bytes(b"bytecode")
    (root / "_localsetup" / ".cache" / "scrapling" / "jobs").mkdir(parents=True)
    (root / "_localsetup" / ".cache" / "scrapling" / "jobs" / "job.json").write_text(
        "{}\n",
        encoding="utf-8",
    )
    (root / "_localsetup" / ".ruff_cache").mkdir()
    (root / "_localsetup" / ".ruff_cache" / "cache.bin").write_bytes(b"cache")
    (root / "_localsetup" / "docs" / "local-context").mkdir(parents=True)
    (root / "_localsetup" / "docs" / "local-context" / "SECRETS_OVERVIEW.md").write_text(
        "Secret ID: mail.box03.example.admin\n",
        encoding="utf-8",
    )
    (root / "_localsetup" / "cached.pyo").write_bytes(b"bytecode")
    npm_token_dir = (
        root
        / "_localsetup"
        / "skills"
        / "ls-npm-management"
        / "scripts"
        / "data"
        / "127_0_0_1_81"
        / "token"
    )
    npm_token_dir.mkdir(parents=True, exist_ok=True)
    (npm_token_dir / "token.txt").write_text("runtime-token\n", encoding="utf-8")
    (npm_token_dir / "expiry.txt").write_text("2099-01-01T00:00:00Z\n", encoding="utf-8")
    workflow_data_dir = (
        root
        / "_localsetup"
        / "workflows"
        / "ls-workflow-ops-tmux-session"
        / "scripts"
        / "data"
    )
    workflow_data_dir.mkdir(parents=True, exist_ok=True)
    (workflow_data_dir / "runtime.txt").write_text("workflow runtime\n", encoding="utf-8")
    (root / "state").mkdir()
    (root / "state" / "inventory.yml").write_text("private inventory\n", encoding="utf-8")
    docs = generate_alias_outputs(root)
    assert docs["count"] > 0
    assert (root / "_localsetup/docs/_generated/workflow-catalog.json").is_file()

    artifact = tmp_path / "localsetup-v3-public.tar.gz"
    package = build_public_artifact(root, artifact)
    assert artifact.exists()
    assert package["leaks"] == []
    assert "_localsetup/__pycache__/cached.pyc" not in package["files"]
    assert "_localsetup/.cache/scrapling/jobs/job.json" not in package["files"]
    assert "_localsetup/docs/local-context/SECRETS_OVERVIEW.md" not in package["files"]
    assert "_localsetup/.ruff_cache/cache.bin" not in package["files"]
    assert "_localsetup/cached.pyo" not in package["files"]
    assert "_localsetup/skills/ls-npm-management/scripts/data/127_0_0_1_81/token/token.txt" not in package["files"]
    assert "_localsetup/skills/ls-npm-management/scripts/data/127_0_0_1_81/token/expiry.txt" not in package["files"]
    assert "_localsetup/workflows/ls-workflow-ops-tmux-session/scripts/data/runtime.txt" not in package["files"]
    assert "state/inventory.yml" not in package["files"]


def test_workflow_catalog_generation_parity_between_paths(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)

    subprocess.run(
        [sys.executable, str(root / "_localsetup/tools/generate_docs_artifacts.py"), "--repo-root", str(root)],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    generated_by_script = json.loads(
        (root / "_localsetup/docs/_generated/workflow-catalog.json").read_text(encoding="utf-8")
    )

    generate_alias_outputs(root)
    generated_by_v3_docs = json.loads(
        (root / "_localsetup/docs/_generated/workflow-catalog.json").read_text(encoding="utf-8")
    )

    assert generated_by_script == workflow_catalog_payload(root)
    assert generated_by_v3_docs == workflow_catalog_payload(root)


def test_lifecycle_status_for_deprecated_and_private_docs() -> None:
    root = Path(__file__).resolve().parents[2]
    review_spec = (root / "_localsetup/docs/WORKFLOW_SKILLS_REVIEW_BUILD_SPEC.md").read_text(encoding="utf-8")
    assert "status: DEPRECATED" in review_spec

    docs_config = (root / "docs.config.yaml").read_text(encoding="utf-8")
    assert 'root: "_localsetup/docs/"' in docs_config
    assert '- "local-context/**"' in docs_config
    assert '- "version"' in docs_config


def test_root_installer_forwards_custom_home(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    root = tmp_path / "repo"
    shutil.copytree(source / "_localsetup", root / "_localsetup", ignore=shutil.ignore_patterns("__pycache__", ".cache"))
    shutil.copy2(source / "install", root / "install")
    home = tmp_path / "custom-home"

    completed = subprocess.run(
        [
            str(root / "install"),
            "--directory",
            str(root),
            "--home",
            str(home),
            "--tools",
            "codex",
            "--yes",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert (home / ".local/share/agents/skills/localsetup/ls-context").is_dir()
    assert (root / ".codex" / "skills").is_symlink()
    assert (home / ".local" / "bin" / "localsetup").is_file()


def test_root_installer_supports_target_directory(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    root = tmp_path / "source"
    target = tmp_path / "target-repo"
    shutil.copytree(source / "_localsetup", root / "_localsetup", ignore=shutil.ignore_patterns("__pycache__", ".cache"))
    shutil.copy2(source / "install", root / "install")
    target.mkdir()
    home = tmp_path / "custom-home"

    completed = subprocess.run(
        [
            str(root / "install"),
            "--directory",
            str(root),
            "--target-directory",
            str(target),
            "--home",
            str(home),
            "--tools",
            "cursor",
            "--yes",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert (home / ".local/share/agents/skills/localsetup/ls-context").is_dir()
    assert (target / ".cursor" / "skills").is_symlink()
    assert (target / "localsetup.lock.json").is_file()
    assert (home / ".local" / "bin" / "localsetup").is_file()
    assert not (root / ".cursor" / "skills").exists()


def test_root_installer_help_mentions_target_directory_and_global_only_defaults() -> None:
    install_path = Path(__file__).resolve().parents[2] / "install"

    completed = subprocess.run(
        [str(install_path), "--help"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "--target-directory PATH" in completed.stdout
    assert "global-only install" in completed.stdout
    assert "Omit for global-only install with no repo adapters" in completed.stdout
    assert "--no-register-shell" in completed.stdout


def make_bootstrap_git_repo(tmp_path: Path) -> Path:
    source = Path(__file__).resolve().parents[2]
    repo = tmp_path / "repo"
    shutil.copytree(source / "_localsetup", repo / "_localsetup", ignore=shutil.ignore_patterns("__pycache__", ".cache"))
    shutil.copy2(source / "VERSION", repo / "VERSION")
    (repo / "README.md").write_text("# Localsetup\n", encoding="utf-8")
    (repo / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, text=True, capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, text=True, capture_output=True, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Localsetup Test", "-c", "user.email=test@example.invalid", "commit", "-m", "init"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    return repo


def test_root_installer_stdin_requires_yes_without_bash_source_warning(tmp_path: Path) -> None:
    install_path = Path(__file__).resolve().parents[2] / "install"
    outside = tmp_path / "outside"
    outside.mkdir()

    with install_path.open("rb") as stdin:
        completed = subprocess.run(
            ["bash"],
            cwd=outside,
            stdin=stdin,
            text=False,
            capture_output=True,
            check=False,
        )

    stderr = completed.stderr.decode()
    assert completed.returncode != 0
    assert stderr.strip() == "Error: v3 install requires --yes. Use _localsetup/tools/localsetup_v3.py plan to preview."
    assert "BASH_SOURCE" not in stderr
    assert "unbound variable" not in stderr


def test_root_installer_stdin_help_without_bash_source_warning(tmp_path: Path) -> None:
    install_path = Path(__file__).resolve().parents[2] / "install"
    outside = tmp_path / "outside"
    outside.mkdir()

    with install_path.open("rb") as stdin:
        completed = subprocess.run(
            ["bash", "-s", "--", "--help"],
            cwd=outside,
            stdin=stdin,
            text=False,
            capture_output=True,
            check=False,
        )

    stderr = completed.stderr.decode()
    stdout = completed.stdout.decode()
    assert completed.returncode == 0
    assert "curl -sSL https://raw.githubusercontent.com/CruxExperts/localsetup/main/install | bash -s -- --yes" in stdout
    assert "--target-directory PATH" in stdout
    assert "BASH_SOURCE" not in stderr
    assert "unbound variable" not in stderr


def test_root_installer_piped_bootstrap_global_only_uses_managed_source(tmp_path: Path) -> None:
    install_path = Path(__file__).resolve().parents[2] / "install"
    bootstrap_repo = make_bootstrap_git_repo(tmp_path / "bootstrap")
    outside = tmp_path / "outside"
    home = tmp_path / "home"
    managed_source = tmp_path / "managed-source"
    outside.mkdir()
    env = {
        **os.environ,
        "LOCALSETUP_BOOTSTRAP_REPO": str(bootstrap_repo),
        "LOCALSETUP_BOOTSTRAP_REF": "main",
        "LOCALSETUP_BOOTSTRAP_SOURCE_DIR": str(managed_source),
    }

    with install_path.open("rb") as stdin:
        completed = subprocess.run(
            ["bash", "-s", "--", "--yes", "--home", str(home)],
            cwd=outside,
            env=env,
            stdin=stdin,
            text=False,
            capture_output=True,
            check=False,
        )

    assert completed.returncode == 0, completed.stderr.decode()
    assert (managed_source / "_localsetup/tools/localsetup_v3.py").is_file()
    assert (home / ".local/share/agents/skills/localsetup/ls-context").is_dir()
    assert (home / ".local/bin/localsetup").is_file()
    assert not (outside / ".codex").exists()
    assert not (outside / "localsetup.lock.json").exists()


def test_root_installer_piped_bootstrap_selected_platform_attaches_caller_target(tmp_path: Path) -> None:
    install_path = Path(__file__).resolve().parents[2] / "install"
    bootstrap_repo = make_bootstrap_git_repo(tmp_path / "bootstrap")
    target = tmp_path / "target"
    home = tmp_path / "home"
    managed_source = tmp_path / "managed-source"
    target.mkdir()
    env = {
        **os.environ,
        "LOCALSETUP_BOOTSTRAP_REPO": str(bootstrap_repo),
        "LOCALSETUP_BOOTSTRAP_REF": "main",
        "LOCALSETUP_BOOTSTRAP_SOURCE_DIR": str(managed_source),
    }

    with install_path.open("rb") as stdin:
        completed = subprocess.run(
            ["bash", "-s", "--", "--yes", "--home", str(home), "--tools", "codex"],
            cwd=target,
            env=env,
            stdin=stdin,
            text=False,
            capture_output=True,
            check=False,
        )

    assert completed.returncode == 0, completed.stderr.decode()
    assert (home / ".local/share/agents/skills/localsetup/ls-context").is_dir()
    assert (target / ".codex" / "skills").is_symlink()
    assert (target / "localsetup.lock.json").is_file()
    assert not (managed_source / ".codex").exists()


def test_root_installer_explicit_bad_directory_does_not_bootstrap(tmp_path: Path) -> None:
    install_path = Path(__file__).resolve().parents[2] / "install"
    bootstrap_repo = make_bootstrap_git_repo(tmp_path / "bootstrap")
    outside = tmp_path / "outside"
    managed_source = tmp_path / "managed-source"
    outside.mkdir()
    env = {
        **os.environ,
        "LOCALSETUP_BOOTSTRAP_REPO": str(bootstrap_repo),
        "LOCALSETUP_BOOTSTRAP_REF": "main",
        "LOCALSETUP_BOOTSTRAP_SOURCE_DIR": str(managed_source),
    }

    completed = subprocess.run(
        [str(install_path), "--directory", str(tmp_path / "missing"), "--yes"],
        cwd=outside,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "directory does not exist" in completed.stderr
    assert not managed_source.exists()


def test_v3_migration_scanner_and_hook_gate(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    (root / "README.md").write_text("Use localsetup-context during migration.\n", encoding="utf-8")

    findings = scan_legacy_references(root)
    assert findings and findings[0]["path"] == "README.md"

    gate = run_maintainer_gate(root, tmp_path / "artifact.tar.gz")
    assert gate["ok"] is True
    assert gate["package"]["leaks"] == []


def test_v3_conservative_migration_renames_managed_legacy_global_skill(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    legacy = home / ".local/share/agents/skills/localsetup/localsetup-context"
    legacy.mkdir(parents=True)
    (legacy / ".localsetup-managed").write_text("source=localsetup-context\n", encoding="utf-8")
    (legacy / "SKILL.md").write_text("---\nname: localsetup-context\n---\n", encoding="utf-8")

    artifacts = detect_legacy_artifacts(root, home=home)
    report = conservative_migrate(root, home=home, backup_dir=tmp_path / "backup")

    assert any(item["kind"] == "legacy_global_skill" for item in artifacts)
    assert report["ok"] is True
    assert not legacy.exists()
    assert (home / ".local/share/agents/skills/localsetup/ls-context/.localsetup-managed").exists()
    assert (tmp_path / "backup" / "migration-report.json").exists()


def test_v3_conservative_migration_refuses_unmanaged_adapter(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    collision = root / ".codex" / "skills"
    collision.mkdir(parents=True)
    (collision / "custom.txt").write_text("user content\n", encoding="utf-8")

    report = conservative_migrate(root, home=home, platform_ids=["codex"], backup_dir=tmp_path / "backup")

    assert report["ok"] is False
    assert report["blockers"]
    assert "mv " in report["blockers"][0]["remediation"]


def test_v3_convert_blocks_unmanaged_adapter_content(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target"
    collision = target / ".codex" / "skills"
    collision.mkdir(parents=True)
    (collision / "custom.txt").write_text("keep\n", encoding="utf-8")

    report = convert_repo(root, home=home, platform_ids=["codex"], target_root=target, apply=False)

    assert report["ok"] is False
    assert any(blocker["kind"] == "adapter_collision" for blocker in report["blockers"])
    assert not (target / "localsetup.lock.json").exists()


def test_v3_convert_archives_old_framework_and_installs_at_target(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target"
    old_framework = target / "_localsetup"
    old_framework.mkdir(parents=True)
    (old_framework / "OLD.txt").write_text("legacy\n", encoding="utf-8")

    report = convert_repo(
        root,
        home=home,
        packs=["core"],
        platform_ids=["codex"],
        target_root=target,
        backup_dir=tmp_path / "backup",
        dependency_mode="prompt-only",
        apply=True,
    )

    assert report["ok"] is True
    assert report["applied"] is True
    assert (tmp_path / "backup" / "repo" / "_localsetup" / "OLD.txt").is_file()
    assert (target / "_localsetup" / "v3" / "cli.py").is_file()
    assert (target / ".codex" / "skills").is_symlink()
    assert (target / "localsetup.lock.json").is_file()
    assert report["verify"]["ok"] is True


def test_v3_convert_framework_sync_excludes_private_runtime_data(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target"
    (root / "_localsetup" / "docs" / "local-context").mkdir(parents=True)
    (root / "_localsetup" / "docs" / "local-context" / "SECRETS.md").write_text("secret\n", encoding="utf-8")
    skill_data = root / "_localsetup" / "skills" / "ls-context" / "scripts" / "data"
    skill_data.mkdir(parents=True)
    (skill_data / "runtime.txt").write_text("runtime\n", encoding="utf-8")
    workflow_data = root / "_localsetup" / "workflows" / "ls-workflow-pipeline-repo-convert" / "scripts" / "data"
    workflow_data.mkdir(parents=True)
    (workflow_data / "runtime.txt").write_text("runtime\n", encoding="utf-8")

    report = convert_repo(root, home=home, platform_ids=["codex"], target_root=target, apply=True)

    assert report["ok"] is True
    assert not (target / "_localsetup" / "docs" / "local-context").exists()
    assert not (target / "_localsetup" / "skills" / "ls-context" / "scripts" / "data").exists()
    assert not (target / "_localsetup" / "workflows" / "ls-workflow-pipeline-repo-convert" / "scripts" / "data").exists()


def test_v3_convert_late_migration_blocker_does_not_remove_target_framework(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target"
    old_framework = target / "_localsetup"
    old_framework.mkdir(parents=True)
    (old_framework / "OLD.txt").write_text("legacy\n", encoding="utf-8")
    legacy = home / ".local/share/agents/skills/localsetup/localsetup-context"
    legacy.mkdir(parents=True)
    (legacy / ".localsetup-managed").write_text("source=localsetup-context\n", encoding="utf-8")
    collision = home / ".local/share/agents/skills/localsetup/ls-context"
    collision.mkdir(parents=True)
    (collision / "SKILL.md").write_text("unmanaged\n", encoding="utf-8")

    report = convert_repo(root, home=home, platform_ids=["codex"], target_root=target, apply=True)

    assert report["ok"] is False
    assert any(blocker["kind"] == "global_skill_collision" for blocker in report["blockers"])
    assert (old_framework / "OLD.txt").is_file()
    assert not (target / ".codex" / "skills").exists()


def test_v3_hook_gate_accepts_mock_runner(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    runner = tmp_path / "mock_runner.sh"
    runner.write_text("#!/usr/bin/env bash\nprintf '{\"ok\": true}\\n'\n", encoding="utf-8")
    runner.chmod(0o755)

    gate = run_maintainer_gate(root, tmp_path / "artifact.tar.gz", runner=str(runner))

    assert gate["ok"] is True
    assert gate["agent_runner"]["returncode"] == 0
    assert gate["agent_runner"]["json"] == {"ok": True}


def test_v3_refuses_unmanaged_skill_collision(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    collision = home / ".local/share/agents/skills/localsetup/ls-context"
    collision.mkdir(parents=True)
    (collision / "SKILL.md").write_text("unmanaged\n", encoding="utf-8")

    plan = build_install_plan(root, home=home, packs=["core"])
    try:
        apply_plan(root, plan, home=home, dry_run=False)
    except RuntimeError as exc:
        assert "unmanaged package path" in str(exc)
    else:
        raise AssertionError("expected unmanaged collision to fail")


def test_rollback_refuses_managed_marker_outside_global_root(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    outside = tmp_path / "outside-managed"
    outside.mkdir()
    (outside / ".localsetup-managed").write_text("source=bad\n", encoding="utf-8")
    (root / "localsetup.lock.json").write_text(
        f"""{{
  "platforms": [],
  "installed_skills": ["{outside}"]
}}
""",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="outside global root"):
        rollback(root, home)


def test_repo_path_rejects_symlink_parent_escape(tmp_path: Path) -> None:
    from _localsetup.v3.paths import PathValidationError, repo_path

    root = tmp_path / "repo"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)

    with pytest.raises(PathValidationError, match="parent escapes"):
        repo_path(root, "link/adapter", "test.path")


def test_tar_leak_scan_detects_private_names(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    leak = root / "_localsetup" / "token.secret"
    leak.write_text("do not ship\n", encoding="utf-8")
    artifact = tmp_path / "localsetup-v3-public.tar.gz"

    package = build_public_artifact(root, artifact)

    assert "_localsetup/token.secret" in package["leaks"]
    assert scan_tar_for_leaks(artifact, [".localsetup-maint"]) == package["leaks"]
