import json
import io
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import _localsetup.v3.apply as apply_mod
import _localsetup.v3.cli as cli_mod
import _localsetup.v3.conversion as conversion_mod
import _localsetup.v3.wizard as wizard
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
from _localsetup.v3.package import build_public_artifact, parse_sha256_file, verify_release_artifact
from _localsetup.v3.plan import build_install_plan
from _localsetup.v3.provenance import MARKER_JSON
from _localsetup.v3.rollback import rollback
from _localsetup.v3.shell import detect_invocation_target, is_managed_shim, register_shell_command, shell_registration_status
from _localsetup.v3.verify import verify_install
from _localsetup.v3.wizard import Choice, TerminalWizard, choose_many, choose_one, run_wizard
from _localsetup.v3.workflows import workflow_catalog_payload


class KeyboardInterruptStream(io.StringIO):
    def readline(self, *args: object, **kwargs: object) -> str:
        raise KeyboardInterrupt


class FakeTtyStringIO(io.StringIO):
    def isatty(self) -> bool:
        return True


class FakeAsciiTtyStringIO(FakeTtyStringIO):
    @property
    def encoding(self) -> str:
        return "ascii"


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
    shutil.copy2(source / "_localsetup" / "requirements.in", repo / "_localsetup" / "requirements.in")
    shutil.copy2(source / "_localsetup" / "requirements.lock", repo / "_localsetup" / "requirements.lock")
    shutil.copy2(source / "VERSION", repo / "VERSION")
    shutil.copytree(source / "assets", repo / "assets")
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
    assert result["transaction"]
    journal = load_json(Path(result["journal"]))
    assert journal["status"] == "committed"
    assert journal["txid"] == result["transaction"]
    assert not (root / ".localsetup" / "staging" / result["transaction"]).exists()
    assert not (home / ".local/share/localsetup/packages/.localsetup-staging" / result["transaction"]).exists()
    assert any(item["kind"] == "staging_root" for item in journal["touched"])

    verify = verify_install(root, home)
    assert verify["ok"] is True
    assert verify["provenance"]["ok"] is True
    assert verify["provenance_warnings"] == []
    assert (home / ".local/share/localsetup/packages/ls-context").is_dir()
    marker = load_json(home / ".local/share/localsetup/packages/ls-context" / MARKER_JSON)
    assert marker["schema_version"] == 1
    assert marker["framework_version"]
    assert marker["source_commit"]
    assert marker["source_tree_sha"]
    assert marker["source_dirty"] in {False, True}
    assert marker["emitter"] == "package-install"
    assert marker["package_name"] == "ls-context"
    assert marker["package_type"] == "skill"
    assert marker["artifact_sha256"] == marker["package_digest"]
    assert marker["artifact_path"] == str(home / ".local/share/localsetup/packages/ls-context")
    assert marker["marker_path"] == str(home / ".local/share/localsetup/packages/ls-context" / MARKER_JSON)
    assert not (home / ".local/share/localsetup/packages/ls-cloudflare-dns").exists()
    assert verify["adapters"] == []
    lock = load_json(root / ".localsetup/lock.json")
    assert lock["platforms"] == []
    assert lock["adapter_state"] == []
    assert lock["package_provenance"]["ls-context"]["package_digest"] == marker["package_digest"]
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
    lock = load_json(root / ".localsetup/lock.json")
    global_root = home / ".local/share/localsetup/packages"

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
    lock = load_json(target / ".localsetup/lock.json")

    assert result["dry_run"] is False
    assert (target / ".cursor" / "skills").is_symlink()
    assert not (root / ".cursor" / "skills").exists()
    assert verify["ok"] is True
    assert {adapter["platform"] for adapter in verify["adapters"]} == {"cursor"}
    assert lock["target_root"] == str(target)
    assert lock["platforms"] == ["cursor"]
    assert not (root / ".localsetup/lock.json").exists()


def test_v3_external_target_install_verify_and_context_freshness_smoke(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "consumer"
    target.mkdir()
    (target / "README.md").write_text("# Consumer repo\n\nLocalsetup context lives here.\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=target, text=True, capture_output=True, check=True)

    plan = build_install_plan(root, home=home, packs=["core"], platform_ids=["codex"], target_root=target)
    apply_plan(root, plan, home=home, target_root=target)
    lock = load_json(target / ".localsetup/lock.json")

    assert lock["source_root"] == str(root)
    assert verify_install(root, home, platform_ids=["codex"], target_root=target)["ok"] is True

    verify_cli = subprocess.run(
        [
            sys.executable,
            str(root / "_localsetup" / "tools" / "localsetup_v3.py"),
            "--repo",
            str(root),
            "--home",
            str(home),
            "--target-directory",
            str(target),
            "verify",
            "--tools",
            "codex",
        ],
        cwd=target,
        text=True,
        capture_output=True,
        check=False,
    )
    assert verify_cli.returncode == 0, verify_cli.stderr + verify_cli.stdout
    assert json.loads(verify_cli.stdout)["ok"] is True

    freshness = subprocess.run(
        [
            sys.executable,
            str(root / "_localsetup" / "tools" / "localsetup_v3.py"),
            "--repo",
            str(root),
            "--home",
            str(home),
            "--target-directory",
            str(target),
            "context-index",
            "freshness",
        ],
        cwd=target,
        text=True,
        capture_output=True,
        check=False,
    )
    assert freshness.returncode == 0, freshness.stderr + freshness.stdout
    payload = json.loads(freshness.stdout)
    assert payload["ok"] is True
    assert payload["contexts"][0]["scope"] == "repo"


def test_v3_verify_levels_and_trace_json(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "consumer"
    target.mkdir()
    plan = build_install_plan(root, home=home, packs=["core"], platform_ids=["codex"], target_root=target)
    apply_plan(root, plan, home=home, target_root=target)
    trace = tmp_path / "trace.jsonl"
    tool = root / "_localsetup" / "tools" / "localsetup_v3.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(tool),
            "--repo",
            str(root),
            "--home",
            str(home),
            "--target-directory",
            str(target),
            "verify",
            "--tools",
            "codex",
            "--level",
            "host",
            "--trace-json",
            str(trace),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["level"] == "host"
    assert any(row.get("status") == "not_run" for row in payload["rules"])
    trace_rows = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    assert trace_rows[-1]["event"] == "verify"


def test_v3_registry_refs_preserve_shared_packages_until_last_rollback(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target_one = tmp_path / "one"
    target_two = tmp_path / "two"
    target_one.mkdir()
    target_two.mkdir()
    apply_plan(root, build_install_plan(root, home=home, packs=["core"], platform_ids=["codex"], target_root=target_one), home=home, target_root=target_one)
    apply_plan(root, build_install_plan(root, home=home, packs=["core"], platform_ids=["kilo"], target_root=target_two), home=home, target_root=target_two)
    managed_skill = home / ".local/share/localsetup/packages/ls-context"
    registry = load_json(home / ".local/share/localsetup/registry.json")
    assert registry["version"] == 2
    assert len(registry["packages"]["ls-context"]["refs"]) == 2
    assert registry["packages"]["ls-context"]["provenance"]["package_name"] == "ls-context"
    assert registry["targets"][str(target_one.resolve())]["package_provenance"]["ls-context"]["package_digest"]

    rollback(root, home=home, target_root=target_one)
    assert managed_skill.is_dir()
    rollback(root, home=home, target_root=target_two)
    assert not managed_skill.exists()


def test_v3_provenance_report_cli_is_report_only(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    apply_plan(root, build_install_plan(root, home=home, packs=["core"], platform_ids=["codex"]), home=home)

    completed = subprocess.run(
        [
            sys.executable,
            "_localsetup/tools/localsetup_v3.py",
            "--source-root",
            str(root),
            "--home",
            str(home),
            "provenance",
            "report",
            "--platforms",
            "codex",
        ],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert "warnings" in payload
    assert "repair_hints" in payload
    assert payload["packages"]["ls-context"]["lock_digest"]
    assert payload["adapters"][0]["provenance_current"] == "global-managed-package"


def test_v3_provenance_report_global_shim_uses_caller_target(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target-repo"
    target.mkdir()
    apply_plan(
        root,
        build_install_plan(root, home=home, packs=["core"], platform_ids=["codex"], target_root=target),
        home=home,
        target_root=target,
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(root / "_localsetup/tools/localsetup_v3.py"),
            "--source-root",
            str(root),
            "--home",
            str(home),
            "provenance",
            "report",
        ],
        cwd=target,
        env={**os.environ, "LOCALSETUP_GLOBAL_SHIM": "1"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["packages"]["ls-context"]["lock_digest"]
    assert payload["adapters"][0]["repo_path"] == str(target / ".codex" / "skills")


def test_v3_detach_removes_adapters_and_preserves_packages(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    tool = root / "_localsetup" / "tools" / "localsetup_v3.py"
    apply_plan(root, build_install_plan(root, home=home, packs=["core"], platform_ids=["codex"]), home=home)

    completed = subprocess.run(
        [sys.executable, str(tool), "--repo", str(root), "--home", str(home), "detach", "--tools", "codex"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["packages_preserved"] is True
    assert not (root / ".codex" / "skills").exists()
    assert (home / ".local/share/localsetup/packages/ls-context").is_dir()


def test_v3_phase3_command_family_outputs_json(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "consumer"
    target.mkdir()
    (target / "package.json").write_text('{"scripts":{"test":"node --test"}}\n', encoding="utf-8")
    tool = root / "_localsetup" / "tools" / "localsetup_v3.py"
    commands = [
        ["skill", "search", "context"],
        ["skill", "info", "ls-context"],
        ["workflow", "search", "audit"],
        ["workflow", "info", "ls-workflow-audit-framework"],
        ["why", "--packs", "core"],
        ["graph"],
        ["audit-global-first"],
        ["adopt", "--target-directory", str(target)],
        ["diff", "--tools", "codex"],
    ]
    for args in commands:
        completed = subprocess.run(
            [sys.executable, str(tool), "--repo", str(root), "--home", str(home), *args],
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, args + [completed.stderr, completed.stdout]
        payload = json.loads(completed.stdout)
        assert isinstance(payload, dict)


def test_v3_global_first_audit_reports_target_legacy_surfaces(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "consumer"
    stale_framework = target / "_localsetup"
    stale_framework.mkdir(parents=True)
    (target / "localsetup.lock.json").write_text('{"version": 1}\n', encoding="utf-8")
    tool = root / "_localsetup" / "tools" / "localsetup_v3.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(tool),
            "--source-root",
            str(root),
            "--home",
            str(home),
            "--target-directory",
            str(target),
            "audit-global-first",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    blocker_kinds = {blocker["kind"] for blocker in payload["blockers"]}
    assert {"stale_framework_source", "legacy_root_lockfile"} <= blocker_kinds
    assert payload["package_root"].endswith(".local/share/localsetup/packages")
    assert payload["registry_path"].endswith(".local/share/localsetup/registry.json")


def test_v3_policy_blocks_high_risk_skill_in_strict_mode(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    skill_md = root / "_localsetup" / "skills" / "ls-context" / "SKILL.md"
    skill_md.write_text(
        "---\nname: ls-context\ndescription: Context.\nrisk: high\npermissions: [filesystem-write]\n---\n",
        encoding="utf-8",
    )
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
            "--policy-mode",
            "strict",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["policy"]["blockers"]


def test_v3_policy_blocks_invalid_risk_metadata_in_strict_mode(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    skill_md = root / "_localsetup" / "skills" / "ls-context" / "SKILL.md"
    skill_md.write_text(
        "---\nname: ls-context\ndescription: Context.\nrisk: critical\n---\n",
        encoding="utf-8",
    )
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
            "--policy-mode",
            "strict",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert any("invalid skill policy metadata" in blocker for blocker in payload["policy"]["blockers"])


def test_v3_sbom_command_writes_source_and_installed_boms(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    apply_plan(root, build_install_plan(root, home=home, packs=["core"]), home=home)
    tool = root / "_localsetup" / "tools" / "localsetup_v3.py"
    source_out = tmp_path / "source.cdx.json"
    installed_out = tmp_path / "installed.cdx.json"

    for args in (
        ["sbom", "--out", str(source_out)],
        ["sbom", "--installed", "--out", str(installed_out)],
    ):
        completed = subprocess.run(
            [sys.executable, str(tool), "--repo", str(root), "--home", str(home), *args],
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr + completed.stdout

    assert json.loads(source_out.read_text(encoding="utf-8"))["bomFormat"] == "CycloneDX"
    assert json.loads(installed_out.read_text(encoding="utf-8"))["components"]


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
    assert (home / ".local/share/localsetup/packages/ls-context").is_dir()
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
    assert (target / ".localsetup/lock.json").is_file()
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
    lock = load_json(target / ".localsetup/lock.json")

    assert result["dry_run"] is False
    assert verify["ok"] is True
    assert verify["adapters"] == []
    assert lock["platforms"] == []
    assert lock["adapter_state"] == []
    assert not (target / ".cursor" / "skills").exists()
    assert any("no platforms were selected" in warning for warning in doctor["warnings"])


def test_v3_install_migrates_legacy_root_lockfile(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "legacy-target"
    target.mkdir()
    legacy_lock = target / "localsetup.lock.json"
    legacy_payload = '{"version": 1, "legacy": true}\n'
    legacy_lock.write_text(legacy_payload, encoding="utf-8")

    plan = build_install_plan(root, home=home, packs=["core"], platform_ids=["codex"], target_root=target)
    result = apply_plan(root, plan, home=home, target_root=target)
    verify = verify_install(root, home, target_root=target)
    lock = load_json(target / ".localsetup" / "lock.json")

    assert result["dry_run"] is False
    assert verify["ok"] is True
    assert not legacy_lock.exists()
    backup = Path(lock["migration_origin"]["backup"])
    assert backup.is_file()
    assert backup.read_text(encoding="utf-8") == legacy_payload


def test_v3_target_templates_use_global_command_surface() -> None:
    root = Path(__file__).resolve().parents[2]
    target_facing_paths = [
        root / "_localsetup" / "skills" / "ls-context" / "SKILL.md",
        root / "_localsetup" / "skills" / "ls-context-index" / "SKILL.md",
        root / "_localsetup" / "skills" / "ls-context-index" / "README.md",
        root / "_localsetup" / "skills" / "ls-context-index" / "docs" / "agent-usage.md",
        root / "_localsetup" / "templates" / "claude-code" / "CLAUDE.md",
        root / "_localsetup" / "templates" / "codex" / "AGENTS.md",
        root / "_localsetup" / "templates" / "cursor" / "ls-context.mdc",
        root / "_localsetup" / "templates" / "kilo" / "AGENTS.md",
        root / "_localsetup" / "templates" / "kilo" / "instructions.md",
        root / "_localsetup" / "templates" / "openclaw" / "OPENCLAW_CONTEXT.md",
        root / "_localsetup" / "templates" / "opencode" / "AGENTS.md",
    ]
    forbidden = [
        "./_localsetup/tools",
        "./_localsetup/tests",
        "python3 _localsetup/tools/localsetup_v3.py",
        "install.ps1",
        "verify_context.ps1",
        "verify_rules.ps1",
        "skill_importer_scan.ps1",
    ]

    offenders: list[str] = []
    for path in target_facing_paths:
        text = path.read_text(encoding="utf-8")
        for needle in forbidden:
            if needle in text:
                offenders.append(f"{path.relative_to(root)}: {needle}")

    assert offenders == []


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
  "data_root": "/tmp/localsetup-data",
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
    assert base.data_root == "/tmp/localsetup-data"
    assert merged.packs == ["core"]
    assert merged.attach_mode == "symlink"
    assert merged.target_directory == "/tmp/localsetup-target"
    assert merged.data_root == "/tmp/localsetup-data"
    assert merged.dependency_mode == "managed-venv"


def test_v3_cli_install_uses_configured_data_root_for_managed_dependencies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    data_root = tmp_path / "runtime-root"
    config_path = tmp_path / "install.json"
    config_path.write_text(
        json.dumps(
            {
                "platforms": [],
                "packs": ["core"],
                "data_root": str(data_root),
                "dependency_mode": "managed-venv",
            }
        ),
        encoding="utf-8",
    )
    captured: list[Path | None] = []

    def fake_ensure_dependencies(
        repo_root: Path,
        *,
        mode: str,
        data_root: Path | None = None,
        runner: object | None = None,
    ) -> dict:
        captured.append(data_root)
        assert repo_root == root
        assert mode == "managed-venv"
        assert data_root is not None
        interpreter = data_root / "venv" / "bin" / "python"
        return {
            "mode": mode,
            "interpreter": str(interpreter),
            "requirements": str(root / "_localsetup" / "requirements.lock"),
            "venv_path": str(data_root / "venv"),
            "lock": {"hash_mode": True},
            "changed": False,
            "pip_check": None,
            "warnings": [],
            "missing": [],
            "commands": [],
            "ok": True,
        }

    monkeypatch.setattr(cli_mod, "ensure_dependencies", fake_ensure_dependencies)

    rc = cli_mod._main(
        [
            "--repo",
            str(root),
            "--home",
            str(home),
            "install",
            "--config",
            str(config_path),
            "--yes",
        ]
    )

    lock = load_json(root / ".localsetup" / "lock.json")
    assert rc == 0
    assert captured == [data_root.resolve()]
    assert lock["python_interpreter"] == str(data_root.resolve() / "venv" / "bin" / "python")


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

    deps = ensure_dependencies(root, mode="managed-venv", data_root=home / ".local/share/localsetup", runner=fake_runner)
    plan = build_install_plan(root, home=home, packs=["core"], platform_ids=["codex"])
    result = apply_plan(root, plan, home=home, dependency_info=deps)
    lock = load_json(root / ".localsetup/lock.json")

    assert any(cmd[1:3] == ["-m", "venv"] for cmd in commands)
    assert any(cmd[2:4] == ["pip", "install"] and "--require-hashes" in cmd and "--only-binary" in cmd for cmd in commands)
    assert any(cmd[-2:] == ["pip", "check"] for cmd in commands)
    assert deps["interpreter"].endswith(".local/share/localsetup/venv/bin/python")
    assert deps["lock"]["hash_mode"] is True
    assert lock["python_interpreter"] == deps["interpreter"]
    assert lock["dependency_state"]["hash_mode"] is True
    assert result["lockfile"].endswith(".localsetup/lock.json")


def test_v3_missing_requirements_checks_selected_interpreter(tmp_path: Path) -> None:
    req = tmp_path / "requirements.txt"
    req.write_text("PGPy>=0.5.4,<0.6\nDefinitely-Missing-Package>=1\n", encoding="utf-8")

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
    assert "localsetup verify --platforms codex" in markdown
    assert "python3 _localsetup/tools/localsetup_v3.py verify" not in markdown


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


def test_v3_self_refresh_defaults_to_all_packs_and_existing_repo_adapters(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    tool = root / "_localsetup" / "tools" / "localsetup_v3.py"

    existing_global = home / ".local" / "share" / "localsetup" / "packages"
    existing_global.mkdir(parents=True, exist_ok=True)
    (root / ".codex").mkdir(parents=True, exist_ok=True)
    (root / ".codex" / "skills").symlink_to(existing_global, target_is_directory=True)
    external_global = home / ".external" / "skills"
    external_global.mkdir(parents=True, exist_ok=True)
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    (root / ".cursor" / "skills").symlink_to(external_global, target_is_directory=True)

    completed = subprocess.run(
        [
            sys.executable,
            str(tool),
            "--repo",
            str(root),
            "--home",
            str(home),
            "self-refresh",
            "--dependency-mode",
            "prompt-only",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert payload["selected"]["platforms"] == ["codex"]
    assert "integrations" in payload["selected"]["packs"]
    assert (home / ".local/share/localsetup/packages/ls-cloudflare-dns").is_dir()
    assert (root / ".codex" / "skills").is_symlink()
    assert payload["verify"]["adapters"][0]["points_to_global"] is True
    assert (root / ".cursor" / "skills").resolve() == external_global


def test_v3_self_refresh_preserves_existing_portable_adapter_mode(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    tool = root / "_localsetup" / "tools" / "localsetup_v3.py"

    portable_adapter = root / ".codex" / "skills"
    portable_adapter.mkdir(parents=True, exist_ok=True)
    (portable_adapter / ".localsetup-portable").write_text("managed_by=localsetup-v3\n", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(tool),
            "--repo",
            str(root),
            "--home",
            str(home),
            "self-refresh",
            "--dependency-mode",
            "prompt-only",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert payload["selected"]["platforms"] == ["codex"]
    assert payload["selected"]["attach_mode"] == "portable"
    assert portable_adapter.is_dir()
    assert not portable_adapter.is_symlink()
    assert (portable_adapter / ".localsetup-portable").is_file()


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
    assert Path(package["sha256"]).is_file()
    assert Path(package["sbom"]).is_file()
    verified = verify_release_artifact(artifact, expected_commit=package["manifest"]["source_commit"])
    assert verified["ok"] is True
    assert any(check["name"] == "sbom" and check["ok"] for check in verified["checks"])
    assert verified["metadata"]["pack_id"] == "localsetup"
    for asset in (
        "assets/README.md",
        "assets/localsetup-v3-readme-hero.png",
        "assets/localsetup-v3-architecture.svg",
        "assets/localsetup-v3-install-lifecycle.svg",
    ):
        assert asset in package["files"]
    assert "assets" in package["manifest"]["public_paths"]
    assert "_localsetup/__pycache__/cached.pyc" not in package["files"]
    assert "_localsetup/.cache/scrapling/jobs/job.json" not in package["files"]
    assert "_localsetup/docs/local-context/SECRETS_OVERVIEW.md" not in package["files"]
    assert "_localsetup/.ruff_cache/cache.bin" not in package["files"]
    assert "_localsetup/cached.pyo" not in package["files"]
    assert "_localsetup/skills/ls-npm-management/scripts/data/127_0_0_1_81/token/token.txt" not in package["files"]
    assert "_localsetup/skills/ls-npm-management/scripts/data/127_0_0_1_81/token/expiry.txt" not in package["files"]
    assert "_localsetup/workflows/ls-workflow-ops-tmux-session/scripts/data/runtime.txt" not in package["files"]
    assert "state/inventory.yml" not in package["files"]


def test_package_command_creates_output_parent(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    artifact = tmp_path / "missing" / "nested" / "localsetup-v3-public.tar.gz"

    package = build_public_artifact(root, artifact)

    assert artifact.is_file()
    assert Path(package["sha256"]).is_file()
    assert Path(package["sbom"]).is_file()


def test_package_command_fails_when_leak_scan_finds_private_file(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    tool = root / "_localsetup" / "tools" / "localsetup_v3.py"
    leak = root / "_localsetup" / "token.secret"
    leak.write_text("do not ship\n", encoding="utf-8")
    artifact = tmp_path / "localsetup-v3-public.tar.gz"

    completed = subprocess.run(
        [sys.executable, str(tool), "--repo", str(root), "package", "--out", str(artifact)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert "_localsetup/token.secret" in payload["leaks"]


def test_verify_release_rejects_missing_or_stale_sbom(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    artifact = tmp_path / "localsetup-v3-public.tar.gz"
    package = build_public_artifact(root, artifact)
    sbom = Path(package["sbom"])
    sbom.unlink()

    missing = verify_release_artifact(artifact)
    assert missing["ok"] is False
    assert any(check["name"] == "sbom" and not check["ok"] for check in missing["checks"])

    sbom.write_text('{"bomFormat":"CycloneDX","metadata":{"component":{"name":"wrong"},"properties":[]},"components":[]}\n', encoding="utf-8")
    stale = verify_release_artifact(artifact)
    assert stale["ok"] is False
    assert any(check["name"] == "sbom" and not check["ok"] for check in stale["checks"])


def test_verify_release_rejects_incomplete_sbom_components(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    artifact = tmp_path / "localsetup-v3-public.tar.gz"
    package = build_public_artifact(root, artifact)
    sbom = Path(package["sbom"])
    payload = json.loads(sbom.read_text(encoding="utf-8"))
    payload["components"] = payload["components"][:-1]
    sbom.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    verified = verify_release_artifact(artifact)

    assert verified["ok"] is False
    sbom_check = next(check for check in verified["checks"] if check["name"] == "sbom")
    assert sbom_check["missing_components"]


def test_parse_sha256_file_accepts_binary_mode_marker(tmp_path: Path) -> None:
    sha = tmp_path / "artifact.sha256"
    sha.write_text("a" * 64 + " *artifact.tar.gz\n", encoding="utf-8")
    digest, name = parse_sha256_file(sha)
    assert digest == "a" * 64
    assert name == "artifact.tar.gz"


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

    generated_by_script.pop("provenance", None)
    generated_by_v3_docs.pop("provenance", None)
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
            "--non-interactive",
            "--yes",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert (home / ".local/share/localsetup/packages/ls-context").is_dir()
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
            "--non-interactive",
            "--yes",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert (home / ".local/share/localsetup/packages/ls-context").is_dir()
    assert (target / ".cursor" / "skills").is_symlink()
    assert (target / ".localsetup/lock.json").is_file()
    assert (home / ".local" / "bin" / "localsetup").is_file()
    assert not (root / ".cursor" / "skills").exists()


def test_root_installer_non_interactive_no_register_shell_skips_shim(tmp_path: Path) -> None:
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
            "--non-interactive",
            "--yes",
            "--no-register-shell",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert (home / ".local/share/localsetup/packages/ls-context").is_dir()
    assert not (home / ".local" / "bin" / "localsetup").exists()


def test_root_installer_non_interactive_visual_flags_keep_json_stdout(tmp_path: Path) -> None:
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
            "--non-interactive",
            "--yes",
            "--no-register-shell",
            "--color",
            "always",
            "--glyphs",
            "unicode",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["attachment"]["platforms"] == []
    assert "\033[" not in completed.stdout
    assert "[OK]" not in completed.stdout


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
    assert "--non-interactive" in completed.stdout
    assert "Automation mode" in completed.stdout
    assert "--no-register-shell" in completed.stdout
    assert "--color MODE" in completed.stdout
    assert "--no-color" in completed.stdout
    assert "--glyphs MODE" in completed.stdout


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


def make_bootstrap_git_repo_with_legacy_commit(tmp_path: Path) -> tuple[Path, str, str]:
    source = Path(__file__).resolve().parents[2]
    repo = tmp_path / "repo"
    tool = repo / "_localsetup" / "tools" / "localsetup_v3.py"
    tool.parent.mkdir(parents=True)
    tool.write_text(
        """#!/usr/bin/env python3
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--home")
parser.add_argument("--repo")
sub = parser.add_subparsers(dest="cmd", required=True)
sub.add_parser("doctor")
sub.add_parser("install")
sub.add_parser("register-shell")
parser.parse_args()
""",
        encoding="utf-8",
    )
    shutil.copy2(source / "VERSION", repo / "VERSION")
    (repo / "README.md").write_text("# Localsetup\n", encoding="utf-8")
    (repo / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, text=True, capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, text=True, capture_output=True, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Localsetup Test", "-c", "user.email=test@example.invalid", "commit", "-m", "legacy"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    legacy_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()

    shutil.rmtree(repo / "_localsetup")
    shutil.copytree(source / "_localsetup", repo / "_localsetup", ignore=shutil.ignore_patterns("__pycache__", ".cache"))
    subprocess.run(["git", "add", "."], cwd=repo, text=True, capture_output=True, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Localsetup Test", "-c", "user.email=test@example.invalid", "commit", "-m", "current"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    current_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    return repo, legacy_commit, current_commit


def run_installer_in_pty(
    command: list[str],
    *,
    input_text: str,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    script = shutil.which("script")
    if script is None:
        pytest.skip("script command is required for pseudo-terminal installer tests")
    log_path = cwd / "installer-pty.log"
    shell_command = " ".join(shlex.quote(part) for part in command)
    return subprocess.run(
        [script, "-q", "-e", "-c", shell_command, str(log_path)],
        input=input_text,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_root_installer_stdin_without_tty_requires_interactive_or_automation(tmp_path: Path) -> None:
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
    assert stderr.strip() == "Error: interactive installer requires a terminal. Run from a TTY, or use --non-interactive --yes for automation."
    assert "BASH_SOURCE" not in stderr
    assert "unbound variable" not in stderr


def test_root_installer_non_interactive_requires_yes_without_bash_source_warning(tmp_path: Path) -> None:
    install_path = Path(__file__).resolve().parents[2] / "install"
    outside = tmp_path / "outside"
    outside.mkdir()

    with install_path.open("rb") as stdin:
        completed = subprocess.run(
            ["bash", "-s", "--", "--non-interactive"],
            cwd=outside,
            stdin=stdin,
            text=False,
            capture_output=True,
            check=False,
        )

    stderr = completed.stderr.decode()
    assert completed.returncode != 0
    assert stderr.strip() == "Error: automation mode requires --non-interactive --yes"
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
    assert "curl -sSL https://raw.githubusercontent.com/CruxExperts/localsetup/main/install | bash -s --" in stdout
    assert "curl -sSL https://raw.githubusercontent.com/CruxExperts/localsetup/main/install | bash -s -- --non-interactive --yes" in stdout
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
            ["bash", "-s", "--", "--non-interactive", "--yes", "--home", str(home)],
            cwd=outside,
            env=env,
            stdin=stdin,
            text=False,
            capture_output=True,
            check=False,
        )

    assert completed.returncode == 0, completed.stderr.decode()
    assert (managed_source / "_localsetup/tools/localsetup_v3.py").is_file()
    assert (home / ".local/share/localsetup/packages/ls-context").is_dir()
    assert (home / ".local/bin/localsetup").is_file()
    assert not (outside / ".codex").exists()
    assert not (outside / ".localsetup/lock.json").exists()


def test_root_installer_refreshes_clean_stale_managed_source_before_wizard(tmp_path: Path) -> None:
    install_path = Path(__file__).resolve().parents[2] / "install"
    bootstrap_repo, legacy_commit, current_commit = make_bootstrap_git_repo_with_legacy_commit(tmp_path / "bootstrap")
    outside = tmp_path / "outside"
    home = tmp_path / "home"
    managed_source = tmp_path / "managed-source"
    outside.mkdir()
    subprocess.run(["git", "clone", str(bootstrap_repo), str(managed_source)], text=True, capture_output=True, check=True)
    subprocess.run(["git", "checkout", "--detach", legacy_commit], cwd=managed_source, text=True, capture_output=True, check=True)
    env = {
        **os.environ,
        "LOCALSETUP_BOOTSTRAP_REPO": str(bootstrap_repo),
        "LOCALSETUP_BOOTSTRAP_REF": "main",
        "LOCALSETUP_BOOTSTRAP_SOURCE_DIR": str(managed_source),
    }

    completed = run_installer_in_pty(
        [str(install_path), "--home", str(home), "--no-register-shell"],
        input_text="\n\nq\n",
        cwd=outside,
        env=env,
    )

    combined = completed.stdout + completed.stderr
    refreshed = subprocess.run(
        ["git", "-C", str(managed_source), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    assert completed.returncode == 130, combined
    assert refreshed == current_commit
    assert "invalid choice: 'wizard'" not in combined


def test_root_installer_refreshes_clean_stale_managed_source_before_non_interactive_install(tmp_path: Path) -> None:
    install_path = Path(__file__).resolve().parents[2] / "install"
    bootstrap_repo, legacy_commit, current_commit = make_bootstrap_git_repo_with_legacy_commit(tmp_path / "bootstrap")
    outside = tmp_path / "outside"
    home = tmp_path / "home"
    managed_source = tmp_path / "managed-source"
    outside.mkdir()
    subprocess.run(["git", "clone", str(bootstrap_repo), str(managed_source)], text=True, capture_output=True, check=True)
    subprocess.run(["git", "checkout", "--detach", legacy_commit], cwd=managed_source, text=True, capture_output=True, check=True)
    env = {
        **os.environ,
        "LOCALSETUP_BOOTSTRAP_REPO": str(bootstrap_repo),
        "LOCALSETUP_BOOTSTRAP_REF": "main",
        "LOCALSETUP_BOOTSTRAP_SOURCE_DIR": str(managed_source),
    }

    completed = subprocess.run(
        [str(install_path), "--non-interactive", "--yes", "--home", str(home), "--no-register-shell"],
        cwd=outside,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    refreshed = subprocess.run(
        ["git", "-C", str(managed_source), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    assert completed.returncode == 0, completed.stderr
    assert refreshed == current_commit
    assert (home / ".local/share/localsetup/packages/ls-context").is_dir()


def test_root_installer_dirty_managed_source_fails_before_refresh(tmp_path: Path) -> None:
    install_path = Path(__file__).resolve().parents[2] / "install"
    bootstrap_repo, legacy_commit, _current_commit = make_bootstrap_git_repo_with_legacy_commit(tmp_path / "bootstrap")
    outside = tmp_path / "outside"
    managed_source = tmp_path / "managed-source"
    outside.mkdir()
    subprocess.run(["git", "clone", str(bootstrap_repo), str(managed_source)], text=True, capture_output=True, check=True)
    subprocess.run(["git", "checkout", "--detach", legacy_commit], cwd=managed_source, text=True, capture_output=True, check=True)
    (managed_source / "local-edit.txt").write_text("do not overwrite\n", encoding="utf-8")
    env = {
        **os.environ,
        "LOCALSETUP_BOOTSTRAP_REPO": str(bootstrap_repo),
        "LOCALSETUP_BOOTSTRAP_REF": "main",
        "LOCALSETUP_BOOTSTRAP_SOURCE_DIR": str(managed_source),
    }

    completed = subprocess.run(
        [str(install_path), "--non-interactive", "--yes"],
        cwd=outside,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "cannot refresh managed bootstrap source because it has uncommitted or untracked changes" in completed.stderr
    assert "--directory PATH" in completed.stderr
    assert (managed_source / "local-edit.txt").read_text(encoding="utf-8") == "do not overwrite\n"


def test_root_installer_non_git_managed_source_fails_actionably(tmp_path: Path) -> None:
    install_path = Path(__file__).resolve().parents[2] / "install"
    bootstrap_repo = make_bootstrap_git_repo(tmp_path / "bootstrap")
    outside = tmp_path / "outside"
    managed_source = tmp_path / "managed-source"
    outside.mkdir()
    (managed_source / "_localsetup" / "tools").mkdir(parents=True)
    (managed_source / "_localsetup" / "tools" / "localsetup_v3.py").write_text("print('stale')\n", encoding="utf-8")
    env = {
        **os.environ,
        "LOCALSETUP_BOOTSTRAP_REPO": str(bootstrap_repo),
        "LOCALSETUP_BOOTSTRAP_REF": "main",
        "LOCALSETUP_BOOTSTRAP_SOURCE_DIR": str(managed_source),
    }

    completed = subprocess.run(
        [str(install_path), "--non-interactive", "--yes"],
        cwd=outside,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "managed bootstrap source exists but is not a Git checkout" in completed.stderr
    assert "Move or remove it, or pass --directory PATH" in completed.stderr


def test_root_installer_unrelated_clean_git_managed_source_fails_without_mutation(tmp_path: Path) -> None:
    install_path = Path(__file__).resolve().parents[2] / "install"
    bootstrap_repo = make_bootstrap_git_repo(tmp_path / "bootstrap")
    outside = tmp_path / "outside"
    managed_source = tmp_path / "managed-source"
    outside.mkdir()
    managed_source.mkdir()
    (managed_source / "README.md").write_text("# Unrelated\n", encoding="utf-8")
    subprocess.run(["git", "init", "-b", "main"], cwd=managed_source, text=True, capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=managed_source, text=True, capture_output=True, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Localsetup Test", "-c", "user.email=test@example.invalid", "commit", "-m", "unrelated"],
        cwd=managed_source,
        text=True,
        capture_output=True,
        check=True,
    )
    before_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=managed_source,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    env = {
        **os.environ,
        "LOCALSETUP_BOOTSTRAP_REPO": str(bootstrap_repo),
        "LOCALSETUP_BOOTSTRAP_REF": "main",
        "LOCALSETUP_BOOTSTRAP_SOURCE_DIR": str(managed_source),
    }

    completed = subprocess.run(
        [str(install_path), "--non-interactive", "--yes"],
        cwd=outside,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    after_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=managed_source,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    assert completed.returncode != 0
    assert "managed bootstrap source exists but is not a Localsetup v3 checkout" in completed.stderr
    assert before_head == after_head
    assert (managed_source / "README.md").read_text(encoding="utf-8") == "# Unrelated\n"
    assert not (managed_source / "_localsetup").exists()


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
            ["bash", "-s", "--", "--non-interactive", "--yes", "--home", str(home), "--tools", "codex"],
            cwd=target,
            env=env,
            stdin=stdin,
            text=False,
            capture_output=True,
            check=False,
        )

    assert completed.returncode == 0, completed.stderr.decode()
    assert (home / ".local/share/localsetup/packages/ls-context").is_dir()
    assert (target / ".codex" / "skills").is_symlink()
    assert (target / ".localsetup/lock.json").is_file()
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
        [str(install_path), "--directory", str(tmp_path / "missing"), "--non-interactive", "--yes"],
        cwd=outside,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "directory does not exist" in completed.stderr
    assert not managed_source.exists()


def test_root_installer_explicit_directory_ignores_managed_source_refresh(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    install_path = source / "install"
    explicit_source = tmp_path / "explicit-source"
    outside = tmp_path / "outside"
    managed_source = tmp_path / "managed-source"
    home = tmp_path / "home"
    shutil.copytree(source / "_localsetup", explicit_source / "_localsetup", ignore=shutil.ignore_patterns("__pycache__", ".cache"))
    shutil.copy2(source / "VERSION", explicit_source / "VERSION")
    outside.mkdir()
    managed_source.mkdir()
    (managed_source / "not-git.txt").write_text("ignored\n", encoding="utf-8")
    env = {
        **os.environ,
        "LOCALSETUP_BOOTSTRAP_REPO": str(tmp_path / "missing-remote"),
        "LOCALSETUP_BOOTSTRAP_REF": "main",
        "LOCALSETUP_BOOTSTRAP_SOURCE_DIR": str(managed_source),
    }

    completed = subprocess.run(
        [
            str(install_path),
            "--directory",
            str(explicit_source),
            "--home",
            str(home),
            "--non-interactive",
            "--yes",
            "--no-register-shell",
        ],
        cwd=outside,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert (managed_source / "not-git.txt").read_text(encoding="utf-8") == "ignored\n"
    assert not (managed_source / ".git").exists()
    assert (home / ".local/share/localsetup/packages/ls-context").is_dir()


def test_root_installer_interactive_preserves_explicit_target_and_no_register_shell(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    root = tmp_path / "source"
    target = tmp_path / "target-repo"
    home = tmp_path / "home"
    shutil.copytree(source / "_localsetup", root / "_localsetup", ignore=shutil.ignore_patterns("__pycache__", ".cache"))
    shutil.copy2(source / "install", root / "install")
    target.mkdir()

    completed = run_installer_in_pty(
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
            "--no-register-shell",
        ],
        input_text="\n\n\n\n1\n1\n1\nyes\n",
        cwd=tmp_path,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert (target / ".cursor" / "skills").is_symlink()
    assert (target / ".localsetup/lock.json").is_file()
    assert not (root / ".cursor" / "skills").exists()
    assert not (home / ".local" / "bin" / "localsetup").exists()


def test_root_installer_interactive_visual_flags_reach_wizard(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    root = tmp_path / "source"
    home = tmp_path / "home"
    shutil.copytree(source / "_localsetup", root / "_localsetup", ignore=shutil.ignore_patterns("__pycache__", ".cache"))
    shutil.copy2(source / "install", root / "install")

    completed = run_installer_in_pty(
        [
            str(root / "install"),
            "--directory",
            str(root),
            "--home",
            str(home),
            "--no-register-shell",
            "--no-color",
            "--glyphs",
            "ascii",
        ],
        input_text="\n\nq\n",
        cwd=tmp_path,
    )

    combined = completed.stdout + completed.stderr
    assert completed.returncode == 130, combined
    assert "\033[1;" not in combined
    assert "\033[0m" not in combined
    assert "[SUGGESTED]" in combined
    assert "★" not in combined
    assert "Install canceled. No changes were applied." in combined


def test_root_installer_interactive_explicit_target_without_platforms_stays_global_only(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    root = tmp_path / "source"
    target = tmp_path / "target-repo"
    home = tmp_path / "home"
    shutil.copytree(source / "_localsetup", root / "_localsetup", ignore=shutil.ignore_patterns("__pycache__", ".cache"))
    shutil.copy2(source / "install", root / "install")
    target.mkdir()

    completed = run_installer_in_pty(
        [
            str(root / "install"),
            "--directory",
            str(root),
            "--target-directory",
            str(target),
            "--home",
            str(home),
            "--no-register-shell",
        ],
        input_text="\n\n\n\n1\n1\n1\nyes\n",
        cwd=tmp_path,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert (home / ".local/share/localsetup/packages/ls-context").is_dir()
    assert (target / ".localsetup/lock.json").is_file()
    assert not (target / ".codex").exists()
    assert not (target / ".cursor").exists()


def test_root_installer_interactive_cancel_does_not_create_home_or_target(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    root = tmp_path / "source"
    target = tmp_path / "target-repo"
    home = tmp_path / "home"
    shutil.copytree(source / "_localsetup", root / "_localsetup", ignore=shutil.ignore_patterns("__pycache__", ".cache"))
    shutil.copy2(source / "install", root / "install")

    completed = run_installer_in_pty(
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
            "--no-register-shell",
        ],
        input_text="q\n",
        cwd=tmp_path,
    )

    assert completed.returncode == 130, completed.stderr + completed.stdout
    assert not home.exists()
    assert not target.exists()


def test_wizard_selection_helpers_accept_numbers_and_back_cancel() -> None:
    term = TerminalWizard(
        input_stream=io.StringIO("2\nb\nq\n"),
        output_stream=io.StringIO(),
        color=False,
    )

    assert choose_one(term, "Mode", [("global", "Global"), ("current", "Current")], default="global") == "current"
    assert choose_many(term, "Platforms", [("codex", "Codex")], default=["codex"]) == "__back__"
    assert choose_one(term, "Mode", [("global", "Global")], default="global") == "__cancel__"


def test_wizard_prompt_returns_cancel_on_keyboard_interrupt() -> None:
    output = io.StringIO()
    term = TerminalWizard(
        input_stream=KeyboardInterruptStream(),
        output_stream=output,
        color=False,
    )

    assert term.prompt("Mode") == "__cancel__"
    assert output.getvalue().endswith("\n")


def test_wizard_color_policy_honors_tty_env_and_explicit_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")

    assert TerminalWizard(io.StringIO(), FakeTtyStringIO(), color_mode="auto").color is True
    assert TerminalWizard(io.StringIO(), io.StringIO(), color_mode="auto").color is False

    monkeypatch.setenv("NO_COLOR", "1")
    assert TerminalWizard(io.StringIO(), FakeTtyStringIO(), color_mode="auto").color is False
    assert TerminalWizard(io.StringIO(), FakeTtyStringIO(), color_mode="always").color is True

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert TerminalWizard(io.StringIO(), io.StringIO(), color_mode="auto").color is True
    assert TerminalWizard(io.StringIO(), FakeTtyStringIO(), color_mode="never").color is False

    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setenv("TERM", "dumb")
    assert TerminalWizard(io.StringIO(), FakeTtyStringIO(), color_mode="auto").color is False


def test_wizard_glyph_policy_uses_ascii_for_scripted_or_ascii_terminals(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")

    legacy_plain = TerminalWizard(io.StringIO(), FakeTtyStringIO(), color=False)
    assert legacy_plain.glyph("ok") == "[OK]"

    scripted = TerminalWizard(io.StringIO(), io.StringIO(), glyph_mode="auto")
    assert scripted.glyph("ok") == "[OK]"

    ascii_tty = TerminalWizard(io.StringIO(), FakeAsciiTtyStringIO(), glyph_mode="auto")
    assert ascii_tty.glyph("suggested") == "[SUGGESTED]"

    unicode_forced = TerminalWizard(io.StringIO(), io.StringIO(), glyph_mode="unicode")
    assert unicode_forced.glyph("ok").startswith("[OK]")
    assert unicode_forced.glyph("ok") != "[OK]"

    ascii_forced = TerminalWizard(io.StringIO(), FakeTtyStringIO(), glyph_mode="ascii")
    assert ascii_forced.glyph("fail") == "[FAIL]"


def test_wizard_semantic_renderer_wraps_paths_and_keeps_text_labels() -> None:
    output = io.StringIO()
    term = TerminalWizard(
        input_stream=io.StringIO(),
        output_stream=output,
        color=False,
        glyph_mode="ascii",
    )

    term.step_header("Platforms", progress="Step 3/7")
    term.key_value_block([("Long path", "/tmp/" + "nested/" * 16 + "repo")])
    term.status_line("ok", "Localsetup installed successfully.")
    term.status_line("warn", "Manual dependency setup may still be needed.")
    term.status_line("fail", "A blocker prevents apply.")
    term.action_list(["Attach selected adapter: /tmp/" + "nested/" * 12 + ".codex/skills"])
    term.diagnostic_command(["python3", "/tmp/" + "nested/" * 12 + "localsetup_v3.py", "doctor"])

    rendered = output.getvalue()
    assert "Step 3/7 - Platforms" in rendered
    assert "Long path:" in rendered
    assert "[OK] Localsetup installed successfully." in rendered
    assert "[WARN] Manual dependency setup may still be needed." in rendered
    assert "[FAIL] A blocker prevents apply." in rendered
    assert "[PLAN] Attach selected adapter:" in rendered
    assert "Diagnostic command:" in rendered
    assert "python3" in rendered


def test_wizard_choice_detail_mode_renders_extended_context() -> None:
    output = io.StringIO()
    term = TerminalWizard(
        input_stream=io.StringIO("1\n"),
        output_stream=output,
        color=False,
    )
    choice = Choice(
        "global",
        "Global library only",
        "Safest default.",
        "Updates the managed skill library.",
        "You want a low-risk install.",
        "No repo adapter paths are created.",
    )

    assert choose_one(term, "Mode", [choice], default="global", decides="Install scope.") == "global"
    rendered = output.getvalue()
    assert "Decides: Install scope." in rendered
    assert "Safest default." in rendered
    assert "Does: Updates the managed skill library." in rendered
    assert "Choose when: You want a low-risk install." in rendered
    assert "Tradeoff: No repo adapter paths are created." in rendered
    assert "Enter number(s) | d details | b back | q quit | ? help" in rendered


def test_wizard_choice_compact_mode_hides_extended_reasoning() -> None:
    output = io.StringIO()
    term = TerminalWizard(
        input_stream=io.StringIO("1\n"),
        output_stream=output,
        color=False,
    )
    term.detail_mode = False
    choice = Choice(
        "core",
        "core",
        "Everyday skills.",
        "Installs the core pack.",
        "You want normal use.",
        "Specialized packs stay out.",
    )

    assert choose_many(term, "Packs", [choice], default=["core"], allow_none=False) == ["core"]
    rendered = output.getvalue()
    assert "Everyday skills." in rendered
    assert "Does: Installs the core pack." not in rendered
    assert "Choose when: You want normal use." not in rendered
    assert "Tradeoff: Specialized packs stay out." not in rendered
    assert "Enter number(s) | d details | b back | q quit | ? help" in rendered


def test_wizard_detail_toggle_rerenders_choices() -> None:
    output = io.StringIO()
    term = TerminalWizard(
        input_stream=io.StringIO("d\n1\n"),
        output_stream=output,
        color=False,
    )
    choice = Choice(
        "symlink",
        "Symlink adapters",
        "Points at managed skills.",
        "Creates repo adapter symlinks.",
        "You want easy updates.",
        "Requires the managed library path.",
    )

    assert choose_one(term, "Adapter mode", [choice], default="symlink") == "symlink"
    rendered = output.getvalue()
    assert "Detail mode: compact." in rendered
    assert rendered.count("Points at managed skills.") == 2
    assert rendered.count("Does: Creates repo adapter symlinks.") == 1
    assert term.detail_mode is False


def test_wizard_help_prints_without_selecting() -> None:
    output = io.StringIO()
    term = TerminalWizard(
        input_stream=io.StringIO("?\n2\n"),
        output_stream=output,
        color=False,
    )

    result = choose_one(
        term,
        "Mode",
        [("global", "Global"), ("current", "Current")],
        default="global",
        help_text="Pick the install scope.",
    )

    assert result == "current"
    rendered = output.getvalue()
    assert "Pick the install scope." in rendered
    assert rendered.count("1. Global") == 2


def test_wizard_selection_helpers_accept_labels_and_comma_lists() -> None:
    term = TerminalWizard(
        input_stream=io.StringIO("Current\ncodex,cursor\nClaude Code\n"),
        output_stream=io.StringIO(),
        color=False,
    )

    assert choose_one(term, "Mode", [("global", "Global"), ("current", "Current")], default="global") == "current"
    assert choose_many(
        term,
        "Platforms",
        [("codex", "Codex"), ("cursor", "Cursor")],
        default=["codex"],
    ) == ["codex", "cursor"]
    assert choose_many(
        term,
        "Platforms",
        [("codex", "Codex"), ("claude-code", "Claude Code")],
        default=["codex"],
    ) == ["claude-code"]


def test_wizard_full_flow_renders_guided_context_for_current_repo(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    source = Path(__file__).resolve().parents[2]
    shutil.copytree(source / "_localsetup" / "docs", root / "_localsetup" / "docs", dirs_exist_ok=True)
    home = tmp_path / "home"
    caller = tmp_path / "caller"
    caller.mkdir()
    output = io.StringIO()
    term = TerminalWizard(
        input_stream=io.StringIO("\n\n2\n1\n1,3\n2\n1\nyes\n"),
        output_stream=output,
        color=False,
    )

    code = run_wizard(
        repo_root=root,
        home=home,
        caller_directory=caller,
        terminal=term,
        register_shell=False,
    )

    rendered = output.getvalue()
    assert code == 0
    assert wizard.WELCOME_BANNER in rendered
    assert "Step 7/7 - Applying" not in rendered
    assert "Step 7/7 - Result" not in rendered
    assert "\nApplying\n" in rendered
    assert "\nResult\n" in rendered
    assert "Source" in rendered
    assert "Install Mode" in rendered
    assert "Platforms" in rendered
    assert "Skill Packs" in rendered
    assert "Options" in rendered
    assert "Review" in rendered
    assert "Result" in rendered
    assert "Decides: Which Localsetup checkout provides the installer files and shipped skills." in rendered
    assert "Suggested: Global library only" in rendered
    assert "Writes adapter path .codex/skills." in rendered
    assert "Code, docs, git, testing, markdown validation, and repo repair workflows." in rendered
    assert "Portable adapter copies" in rendered
    assert "Managed virtual environment" in rendered
    assert "Does: Shows source, target, packs, adapter mode, dependency mode, and concrete" in rendered
    assert "filesystem actions before changes." in rendered
    assert "Does: Verification checked the managed library and selected adapter paths after applying" in rendered
    assert "the plan." in rendered
    assert "Enter number(s) | d details | b back | q quit | ? help" in rendered
    assert (caller / ".codex" / "skills").exists()


def test_wizard_tty_output_clears_screen_before_banner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    output = FakeTtyStringIO()
    term = TerminalWizard(
        input_stream=io.StringIO("q\n"),
        output_stream=output,
        color=False,
    )
    monkeypatch.setenv("TERM", "xterm-256color")

    code = run_wizard(repo_root=root, home=home, terminal=term)

    assert code == 130
    assert output.getvalue().startswith("\033[2J\033[3J\033[H" + wizard.WELCOME_BANNER)


def test_wizard_scripted_output_does_not_clear_screen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    output = io.StringIO()
    term = TerminalWizard(
        input_stream=io.StringIO("q\n"),
        output_stream=output,
        color=False,
    )
    monkeypatch.setenv("TERM", "xterm-256color")

    code = run_wizard(repo_root=root, home=home, terminal=term)

    assert code == 130
    assert "\033[2J" not in output.getvalue()
    assert output.getvalue().startswith(wizard.WELCOME_BANNER)


def test_wizard_cancel_exits_without_applying(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    term = TerminalWizard(
        input_stream=io.StringIO("q\n"),
        output_stream=io.StringIO(),
        color=False,
    )

    code = run_wizard(repo_root=root, home=home, terminal=term)

    assert code == 130
    assert not (home / ".local/share/localsetup/packages").exists()


def test_wizard_keyboard_interrupt_before_apply_exits_without_applying(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    output = io.StringIO()
    term = TerminalWizard(
        input_stream=KeyboardInterruptStream(),
        output_stream=output,
        color=False,
    )

    code = run_wizard(repo_root=root, home=home, terminal=term)

    assert code == 130
    assert "Install canceled. No changes were applied." in output.getvalue()
    assert not (home / ".local/share/localsetup/packages").exists()


def test_wizard_keyboard_interrupt_during_apply_warns_partial_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_temp_repo(tmp_path)
    source = Path(__file__).resolve().parents[2]
    shutil.copytree(source / "_localsetup" / "docs", root / "_localsetup" / "docs", dirs_exist_ok=True)
    home = tmp_path / "home"
    output = io.StringIO()
    term = TerminalWizard(
        input_stream=io.StringIO("\n\n1\n1\n1\n1\nyes\n"),
        output_stream=output,
        color=False,
    )

    def interrupt_apply(term: TerminalWizard, state: wizard.WizardState) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr(wizard, "_apply_and_show_result", interrupt_apply)

    code = run_wizard(repo_root=root, home=home, terminal=term, register_shell=False)

    rendered = output.getvalue()
    assert code == 130
    assert "Install interrupted during apply. Some changes may have been applied" in rendered
    assert "Install canceled. No changes were applied." not in rendered


def test_wizard_global_only_apply_with_scripted_confirmation(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    source = Path(__file__).resolve().parents[2]
    shutil.copytree(source / "_localsetup" / "docs", root / "_localsetup" / "docs", dirs_exist_ok=True)
    home = tmp_path / "home"
    term = TerminalWizard(
        input_stream=io.StringIO("\n\n1\n1\n1\n1\nyes\n"),
        output_stream=io.StringIO(),
        color=False,
    )

    code = run_wizard(repo_root=root, home=home, terminal=term, register_shell=False)

    assert code == 0
    assert (home / ".local/share/localsetup/packages/ls-context").is_dir()
    assert not (root / ".codex").exists()


def test_wizard_explicit_target_is_default_when_provided(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    source = Path(__file__).resolve().parents[2]
    shutil.copytree(source / "_localsetup" / "docs", root / "_localsetup" / "docs", dirs_exist_ok=True)
    home = tmp_path / "home"
    caller = tmp_path / "caller"
    target = tmp_path / "target"
    caller.mkdir()
    target.mkdir()
    term = TerminalWizard(
        input_stream=io.StringIO("\n\n\n\n1\n1\n1\nyes\n"),
        output_stream=io.StringIO(),
        color=False,
    )

    code = run_wizard(
        repo_root=root,
        home=home,
        caller_directory=caller,
        target_directory=target,
        target_directory_is_explicit=True,
        platforms=["cursor"],
        terminal=term,
        register_shell=False,
    )

    assert code == 0
    assert (target / ".cursor" / "skills").is_symlink()
    assert (target / ".localsetup/lock.json").is_file()
    assert not (caller / ".cursor").exists()


def test_wizard_explicit_target_without_platforms_defaults_global_only(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    source = Path(__file__).resolve().parents[2]
    shutil.copytree(source / "_localsetup" / "docs", root / "_localsetup" / "docs", dirs_exist_ok=True)
    home = tmp_path / "home"
    caller = tmp_path / "caller"
    target = tmp_path / "target"
    caller.mkdir()
    target.mkdir()
    term = TerminalWizard(
        input_stream=io.StringIO("\n\n\n\n1\n1\n1\nyes\n"),
        output_stream=io.StringIO(),
        color=False,
    )

    code = run_wizard(
        repo_root=root,
        home=home,
        caller_directory=caller,
        target_directory=target,
        target_directory_is_explicit=True,
        terminal=term,
        register_shell=False,
    )

    assert code == 0
    assert (target / ".localsetup/lock.json").is_file()
    assert not (target / ".codex").exists()
    assert not (caller / ".codex").exists()


def test_v3_migration_scanner_and_hook_gate(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    (root / "README.md").write_text("Use localsetup-context during migration.\n", encoding="utf-8")
    runtime_note = root / ".codex" / "runs" / "20260512-note.md"
    runtime_note.parent.mkdir(parents=True)
    runtime_note.write_text("Use localsetup-context in runtime notes only.\n", encoding="utf-8")
    heartbeat_note = root / ".localsetup" / "state" / "codex-heartbeat" / "latest.json"
    heartbeat_note.parent.mkdir(parents=True)
    heartbeat_note.write_text('{"note": "Use localsetup-context in runtime state only."}\n', encoding="utf-8")

    findings = scan_legacy_references(root)
    paths = {finding["path"] for finding in findings}
    assert "README.md" in paths
    assert ".codex/runs/20260512-note.md" not in paths
    assert ".localsetup/state/codex-heartbeat/latest.json" not in paths

    gate = run_maintainer_gate(root, tmp_path / "artifact.tar.gz")
    assert gate["ok"] is True
    assert gate["package"]["leaks"] == []


def test_v3_conservative_migration_renames_managed_legacy_global_skill(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    legacy = home / ".local/share/localsetup/packages/localsetup-context"
    legacy.mkdir(parents=True)
    (legacy / ".localsetup-managed").write_text("source=localsetup-context\n", encoding="utf-8")
    (legacy / "SKILL.md").write_text("---\nname: localsetup-context\n---\n", encoding="utf-8")

    artifacts = detect_legacy_artifacts(root, home=home)
    report = conservative_migrate(root, home=home, backup_dir=tmp_path / "backup")

    assert any(item["kind"] == "legacy_global_skill" for item in artifacts)
    assert report["ok"] is True
    assert not legacy.exists()
    assert (home / ".local/share/localsetup/packages/ls-context" / MARKER_JSON).exists()
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
    assert not (target / ".localsetup/lock.json").exists()


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
    assert not (target / "_localsetup").exists()
    assert (target / ".codex" / "skills").is_symlink()
    assert (target / ".localsetup/lock.json").is_file()
    assert report["verify"]["ok"] is True


def test_v3_convert_does_not_copy_framework_source(tmp_path: Path) -> None:
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
    assert report["framework_source"]["copied"] is False
    assert not (target / "_localsetup").exists()


def test_v3_convert_managed_venv_uses_configured_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "custom-home"
    target = tmp_path / "target"
    commands: list[list[str]] = []

    def fake_runner(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        commands.append(cmd)
        if cmd[1:3] == ["-m", "venv"]:
            python_path = Path(cmd[3]) / "bin" / "python"
            python_path.parent.mkdir(parents=True, exist_ok=True)
            python_path.write_text("# fake python\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    def fake_ensure_dependencies(repo_root: Path, *, mode: str, data_root: Path | None = None, runner: object | None = None) -> dict:
        return ensure_dependencies(repo_root, mode=mode, data_root=data_root, runner=fake_runner)

    monkeypatch.setattr(conversion_mod, "ensure_dependencies", fake_ensure_dependencies)

    report = convert_repo(
        root,
        home=home,
        packs=["core"],
        platform_ids=["codex"],
        target_root=target,
        dependency_mode="managed-venv",
        apply=True,
    )

    interpreter = report["install"]["dependencies"]["interpreter"]
    assert report["ok"] is True
    assert any(cmd[1:3] == ["-m", "venv"] for cmd in commands)
    assert interpreter.endswith(".local/share/localsetup/venv/bin/python")
    assert str(home) in interpreter


def test_v3_convert_late_migration_blocker_does_not_remove_target_framework(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target"
    old_framework = target / "_localsetup"
    old_framework.mkdir(parents=True)
    (old_framework / "OLD.txt").write_text("legacy\n", encoding="utf-8")
    legacy = home / ".local/share/localsetup/packages/localsetup-context"
    legacy.mkdir(parents=True)
    (legacy / ".localsetup-managed").write_text("source=localsetup-context\n", encoding="utf-8")
    collision = home / ".local/share/localsetup/packages/ls-context"
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
    collision = home / ".local/share/localsetup/packages/ls-context"
    collision.mkdir(parents=True)
    (collision / "SKILL.md").write_text("unmanaged\n", encoding="utf-8")

    plan = build_install_plan(root, home=home, packs=["core"])
    try:
        apply_plan(root, plan, home=home, dry_run=False)
    except RuntimeError as exc:
        assert "unmanaged package path" in str(exc)
    else:
        raise AssertionError("expected unmanaged collision to fail")


def test_v3_failed_apply_marks_journal_and_cleans_staging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    plan = build_install_plan(root, home=home, packs=["core"])
    original_replace = apply_mod._same_filesystem_replace

    def fail_first_replace(src: Path, dest: Path) -> None:
        if dest.name == "ls-context":
            raise OSError("simulated replace failure")
        original_replace(src, dest)

    monkeypatch.setattr(apply_mod, "_same_filesystem_replace", fail_first_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        apply_plan(root, plan, home=home, dry_run=False)

    journals = sorted((root / ".localsetup" / "install-journal").glob("*.json"))
    assert journals
    journal = load_json(journals[-1])
    assert journal["status"] == "failed"
    assert "simulated replace failure" in journal["error"]
    for item in journal["touched"]:
        if item.get("kind") == "staging_root":
            assert not Path(item["staging_root"]).exists()


def test_v3_failed_package_promotion_restores_existing_managed_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    plan = build_install_plan(root, home=home, packs=["core"])
    apply_plan(root, plan, home=home, dry_run=False)
    installed = home / ".local/share/localsetup/packages/ls-context"
    original_skill_md = installed / "SKILL.md"
    original_text = original_skill_md.read_text(encoding="utf-8")
    original_replace = apply_mod._same_filesystem_replace

    def fail_promotion(src: Path, dest: Path) -> None:
        if src.name == "ls-context" and src.parent.name == "skills" and dest.name == "ls-context":
            raise OSError("simulated promotion failure")
        original_replace(src, dest)

    monkeypatch.setattr(apply_mod, "_same_filesystem_replace", fail_promotion)

    with pytest.raises(OSError, match="simulated promotion failure"):
        apply_plan(root, plan, home=home, dry_run=False)

    assert installed.is_dir()
    assert original_skill_md.read_text(encoding="utf-8") == original_text
    assert not list((home / ".local/share/localsetup/packages").glob(".ls-context.localsetup-backup-*"))
    journals = sorted((root / ".localsetup" / "install-journal").glob("*.json"))
    assert load_json(journals[-1])["status"] == "failed"


def test_v3_failed_late_commit_restores_packages_and_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    plan = build_install_plan(root, home=home, packs=["core"])
    apply_plan(root, plan, home=home, dry_run=False)
    installed = home / ".local/share/localsetup/packages/ls-context"
    original_text = (installed / "SKILL.md").read_text(encoding="utf-8")
    registry_path = home / ".local/share/localsetup/registry.json"
    original_registry = registry_path.read_text(encoding="utf-8")
    (root / "_localsetup" / "skills" / "ls-context" / "SKILL.md").write_text(
        "---\nname: ls-context\ndescription: Changed.\n---\nchanged\n",
        encoding="utf-8",
    )
    original_save_json = apply_mod.save_json

    def fail_lock_save(path: Path, payload: dict) -> None:
        if path.name == "lock.json" and path.parent.name == ".localsetup":
            raise OSError("simulated lockfile failure")
        original_save_json(path, payload)

    monkeypatch.setattr(apply_mod, "save_json", fail_lock_save)

    with pytest.raises(OSError, match="simulated lockfile failure"):
        apply_plan(root, plan, home=home, dry_run=False)

    assert (installed / "SKILL.md").read_text(encoding="utf-8") == original_text
    assert registry_path.read_text(encoding="utf-8") == original_registry
    journals = sorted((root / ".localsetup" / "install-journal").glob("*.json"))
    assert load_json(journals[-1])["status"] == "failed"


def test_v3_failed_adapter_replace_restores_existing_adapter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    plan = build_install_plan(root, home=home, packs=["core"], attach_mode="portable", platform_ids=["codex"])
    apply_plan(root, plan, home=home, dry_run=False)
    adapter = root / ".codex" / "skills"
    existing_note = adapter / "existing.txt"
    existing_note.write_text("keep me\n", encoding="utf-8")
    original_copytree = apply_mod.shutil.copytree

    def fail_adapter_copy(src: Path, dst: Path, *args: object, **kwargs: object):
        if dst == adapter:
            raise OSError("simulated adapter copy failure")
        return original_copytree(src, dst, *args, **kwargs)

    monkeypatch.setattr(apply_mod.shutil, "copytree", fail_adapter_copy)

    with pytest.raises(OSError, match="simulated adapter copy failure"):
        apply_plan(root, plan, home=home, dry_run=False)

    assert (adapter / ".localsetup-portable").is_file()
    assert existing_note.read_text(encoding="utf-8") == "keep me\n"
    journals = sorted((root / ".localsetup" / "install-journal").glob("*.json"))
    assert load_json(journals[-1])["status"] == "failed"


def test_rollback_refuses_managed_marker_outside_global_root(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    outside = tmp_path / "outside-managed"
    outside.mkdir()
    (outside / ".localsetup-managed").write_text("source=bad\n", encoding="utf-8")
    (root / ".localsetup").mkdir()
    (root / ".localsetup/lock.json").write_text(
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
