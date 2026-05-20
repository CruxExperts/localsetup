import json
import io
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import _localsetup.core.apply as apply_mod
import _localsetup.core.cli as cli_mod
import _localsetup.core.conversion as conversion_mod
import _localsetup.core.wizard as wizard
from _localsetup.core.apply import apply_plan
from _localsetup.core.boundary import scan_tar_for_leaks
from _localsetup.core.cli import _split_csv
from _localsetup.core.config import InstallConfig, load_install_config, merge_cli_config
from _localsetup.core.context import build_agent_context, render_markdown_report
from _localsetup.core.conversion import convert_repo
from _localsetup.core.dependencies import ensure_dependencies
from _localsetup.core.doctor import run_doctor
from _localsetup.core.docs import generate_alias_outputs
from _localsetup.core.hooks import run_maintainer_gate
from _localsetup.core.lockfile import load_json
from _localsetup.core.migration import conservative_migrate, detect_legacy_artifacts, scan_legacy_references
from _localsetup.core.package import build_public_artifact, parse_sha256_file, verify_release_artifact
from _localsetup.core.plan import build_install_plan
from _localsetup.core.provenance import MARKER_JSON
from _localsetup.core.rollback import rollback
from _localsetup.core.schema import validate_json_schema
from _localsetup.core.shell import detect_invocation_target, is_managed_shim, register_shell_command, shell_registration_status
from _localsetup.core.skills import skill_taxonomy_payload
from _localsetup.core.verify import verify_install
from _localsetup.core.wizard import Choice, TerminalWizard, choose_many, choose_many_checkbox, choose_one, run_wizard
from _localsetup.core.workflows import workflow_catalog_payload


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


class FakeKeyInput:
    def __init__(self, text: str) -> None:
        self.text = text
        self.offset = 0

    @property
    def remaining(self) -> bool:
        return self.offset < len(self.text)

    def read(self, size: int = 1) -> str:
        if not self.remaining:
            return ""
        value = self.text[self.offset : self.offset + size]
        self.offset += len(value)
        return value

    def fileno(self) -> int:
        return 0

    def isatty(self) -> bool:
        return True


def patch_fake_key_input(monkeypatch: pytest.MonkeyPatch, stream: FakeKeyInput) -> None:
    def fake_select(
        read_fds: list[int], write_fds: list[int], error_fds: list[int], timeout: float | None = None
    ) -> tuple[list[int], list[int], list[int]]:
        return (read_fds if stream.remaining else [], write_fds, error_fds)

    monkeypatch.setattr(wizard.select, "select", fake_select)


def enable_checkbox_key_mode(monkeypatch: pytest.MonkeyPatch, stream: FakeKeyInput) -> None:
    patch_fake_key_input(monkeypatch, stream)
    monkeypatch.setattr(wizard, "_can_use_checkbox_keys", lambda term: True)
    monkeypatch.setattr(wizard.termios, "tcgetattr", lambda fd: [])
    monkeypatch.setattr(wizard.termios, "tcsetattr", lambda fd, when, settings: None)
    monkeypatch.setattr(wizard.tty, "setcbreak", lambda fd: None)


def make_temp_repo(tmp_path: Path) -> Path:
    source = Path(__file__).resolve().parents[2]
    repo = tmp_path / "repo"
    (repo / "_localsetup").mkdir(parents=True)
    shutil.copytree(source / "_localsetup" / "config", repo / "_localsetup" / "config")
    shutil.copytree(source / "_localsetup" / "core", repo / "_localsetup" / "core")
    shutil.copytree(source / "_localsetup" / "skills", repo / "_localsetup" / "skills")
    shutil.copytree(source / "_localsetup" / "workflows", repo / "_localsetup" / "workflows")
    shutil.copytree(source / "_localsetup" / "tools", repo / "_localsetup" / "tools")
    shutil.copy2(source / "VERSION", repo / "VERSION")
    shutil.copy2(source / "pyproject.toml", repo / "pyproject.toml")
    shutil.copy2(source / "uv.lock", repo / "uv.lock")
    shutil.copytree(source / "assets", repo / "assets")
    (repo / "_localsetup" / "docs" / "_generated").mkdir(parents=True)
    (repo / "_localsetup" / "docs" / "migration").mkdir(parents=True)
    for rel_path in ("README.md", "FEATURES.md", "PLATFORM_REGISTRY.md"):
        shutil.copy2(source / "_localsetup" / "docs" / rel_path, repo / "_localsetup" / "docs" / rel_path)
    (repo / ".github").mkdir()
    (repo / "README.md").write_text("# Localsetup\n", encoding="utf-8")
    (repo / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
    return repo


def assert_scoped_adapter(path: Path, *packages: str) -> None:
    assert path.is_dir()
    assert not path.is_symlink()
    assert (path / ".localsetup-adapter.json").is_file()
    for package in packages:
        assert (path / package).is_symlink() or (path / package).is_dir()


def test_plan_apply_verify_rollback(tmp_path: Path) -> None:
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


def test_selected_workflows_install_as_skill_packages(tmp_path: Path) -> None:
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


def test_selection_resolves_preset_classes_tags_skills_and_exclusions(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"

    plan = build_install_plan(
        root,
        home=home,
        preset="custom",
        skills=["localsetup-context"],
        skill_classes=["operations"],
        skill_tags=["git"],
        exclude_skills=["ls-linux-patcher"],
    )

    selected = set(plan.rollback_metadata["skills"])
    assert "ls-context" in selected
    assert "ls-git-workflows" in selected
    assert "ls-system-info" in selected
    assert "ls-linux-patcher" not in selected
    assert plan.rollback_metadata["packs"] == []
    assert plan.rollback_metadata["selectors"]["skill_classes"] == ["operations"]
    assert plan.rollback_metadata["selectors"]["skill_tags"] == ["git"]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"preset": "unknown"}, "unknown preset: unknown"),
        ({"packs": ["unknown"]}, "unknown pack"),
        ({"skill_classes": ["unknown"]}, "unknown skill class"),
        ({"skill_tags": ["unknown"]}, "unknown skill tag"),
        ({"skills": ["unknown"]}, "unknown skill selector: unknown"),
        ({"exclude_skills": ["unknown"]}, "unknown excluded skill: unknown"),
    ],
)
def test_selection_rejects_unknown_selectors(tmp_path: Path, kwargs: dict, message: str) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"

    with pytest.raises(ValueError, match=message):
        build_install_plan(root, home=home, **kwargs)


def test_selection_keeps_workflow_required_skills_after_exclusion(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"

    plan = build_install_plan(
        root,
        home=home,
        packs=["publishing"],
        exclude_skills=["ls-framework-audit"],
    )

    assert "ls-workflow-pipeline-pre-publish" in plan.rollback_metadata["workflows"]
    assert "ls-framework-audit" in plan.rollback_metadata["skills"]
    assert plan.rollback_metadata["selectors"]["exclude_skills"] == ["ls-framework-audit"]


def test_scoped_adapter_exposes_only_selected_packages_even_when_global_has_more(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"

    apply_plan(
        root,
        build_install_plan(root, home=home, global_packs=["dev"], repo_packs=["core"], platform_ids=["codex"]),
        home=home,
    )

    global_root = home / ".local/share/localsetup/packages"
    adapter = root / ".codex" / "skills"
    assert (global_root / "ls-nodejs-nextjs").is_dir()
    assert_scoped_adapter(adapter, "ls-context")
    assert not (adapter / "ls-nodejs-nextjs").exists()
    assert verify_install(root, home, platform_ids=["codex"])["ok"] is True
    doctor = run_doctor(root, home=home)
    assert not any(
        artifact["kind"] == "unmanaged_adapter" and Path(artifact["path"]) == adapter
        for artifact in doctor["legacy"]["artifacts"]
    )


def test_split_global_and_repo_packs_install_union_but_expose_repo_subset(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"

    plan = build_install_plan(
        root,
        home=home,
        global_packs=["dev"],
        repo_packs=["core"],
        platform_ids=["codex"],
    )
    apply_plan(root, plan, home=home)

    global_root = home / ".local/share/localsetup/packages"
    adapter = root / ".codex" / "skills"
    lock = load_json(root / ".localsetup/lock.json")
    registry = load_json(home / ".local/share/localsetup/registry.json")

    assert (global_root / "ls-nodejs-nextjs").is_dir()
    assert (global_root / "ls-context").is_dir()
    assert (adapter / "ls-context").exists()
    assert not (adapter / "ls-nodejs-nextjs").exists()
    assert "ls-nodejs-nextjs" in lock["global_baseline_packages"]
    assert "ls-nodejs-nextjs" not in lock["repo_packages"]
    assert lock["adapter_packages"] == lock["repo_packages"]
    assert lock["adapter_targets"][0]["packages"] == lock["repo_packages"]
    assert "ls-nodejs-nextjs" in registry["global_baseline"]["packages"]
    assert "ls-nodejs-nextjs" not in registry["targets"][str(root.resolve())]["repo_selection"]["packages"]
    assert verify_install(root, home, platform_ids=["codex"])["ok"] is True


def test_legacy_selector_flags_apply_to_global_and_repo_selection(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"

    apply_plan(root, build_install_plan(root, home=home, packs=["dev"], platform_ids=["codex"]), home=home)

    lock = load_json(root / ".localsetup/lock.json")
    assert "ls-nodejs-nextjs" in lock["global_baseline_packages"]
    assert "ls-nodejs-nextjs" in lock["repo_packages"]
    assert (root / ".codex" / "skills" / "ls-nodejs-nextjs").exists()


def test_global_selector_aliases_do_not_imply_repo_visibility(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"

    apply_plan(root, build_install_plan(root, home=home, global_packs=["dev"], platform_ids=["codex"]), home=home)

    lock = load_json(root / ".localsetup/lock.json")
    adapter = root / ".codex" / "skills"

    assert "ls-nodejs-nextjs" in lock["global_baseline_packages"]
    assert "ls-nodejs-nextjs" not in lock["repo_packages"]
    assert (home / ".local/share/localsetup/packages/ls-nodejs-nextjs").is_dir()
    assert not (adapter / "ls-nodejs-nextjs").exists()
    assert (adapter / "ls-context").exists()


def test_scoped_adapter_detects_tampered_child_symlink(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"

    apply_plan(root, build_install_plan(root, home=home, packs=["core"], platform_ids=["codex"]), home=home)

    adapter = root / ".codex" / "skills"
    bad_target = tmp_path / "elsewhere" / "ls-context"
    bad_target.mkdir(parents=True)
    (bad_target / "SKILL.md").write_text("---\nname: ls-context\n---\n", encoding="utf-8")
    (adapter / "ls-context").unlink()
    (adapter / "ls-context").symlink_to(bad_target, target_is_directory=True)

    verify = verify_install(root, home, platform_ids=["codex"])
    doctor = run_doctor(root, home=home, platform_ids=["codex"])

    assert verify["ok"] is False
    assert any("adapter package target mismatch" in issue for issue in verify["issues"])
    assert any(
        warning == "scoped adapter package target differs from managed package: ls-context"
        for warning in verify["provenance_warnings"]
    )
    assert doctor["ok"] is False
    assert any("adapter package target mismatch (ls-context)" in blocker for blocker in doctor["blockers"])


@pytest.mark.parametrize(
    ("attach_mode", "marker_text", "reason"),
    [
        ("symlink", "{not-json", "adapter marker is not valid JSON"),
        ("symlink", '{"version": 1}', "adapter marker has unsupported mode"),
        ("symlink", '{"mode": "elsewhere"}', "adapter marker has unsupported mode"),
        ("portable", "{not-json", "adapter marker is not valid JSON"),
        ("portable", '{"version": 1}', "adapter marker has unsupported mode"),
        ("portable", '{"mode": "elsewhere"}', "adapter marker has unsupported mode"),
    ],
)
def test_adapter_invalid_marker_fails_integrity(
    tmp_path: Path, attach_mode: str, marker_text: str, reason: str
) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"

    apply_plan(
        root,
        build_install_plan(root, home=home, packs=["core"], attach_mode=attach_mode, platform_ids=["codex"]),
        home=home,
    )
    adapter = root / ".codex" / "skills"
    (adapter / ".localsetup-adapter.json").write_text(marker_text, encoding="utf-8")

    verify = verify_install(root, home, platform_ids=["codex"])
    doctor = run_doctor(root, home=home)

    assert verify["ok"] is False
    assert any(reason in str(failure.get("reason")) for failure in verify["adapters"][0]["package_integrity_failures"])
    assert any("scoped adapter integrity failure" in warning and reason in warning for warning in verify["provenance_warnings"])
    assert doctor["ok"] is False
    assert any("adapter package target mismatch (adapter marker)" in blocker for blocker in doctor["blockers"])


def test_legacy_managed_global_symlink_is_migrated_to_scoped_adapter(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    legacy_root = home / ".local/share/agents/skills/localsetup"
    legacy_root.mkdir(parents=True)
    adapter = root / ".codex" / "skills"
    adapter.parent.mkdir(parents=True)
    adapter.symlink_to(legacy_root, target_is_directory=True)

    apply_plan(root, build_install_plan(root, home=home, packs=["core"], platform_ids=["codex"]), home=home)

    assert_scoped_adapter(adapter, "ls-context")
    assert not adapter.is_symlink()
    assert verify_install(root, home, platform_ids=["codex"])["ok"] is True


def test_portable_mode_uses_managed_copies(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)

    plan = build_install_plan(root, home=home, packs=["core"], attach_mode="portable", platform_ids=["codex"])
    result = apply_plan(root, plan, home=home, dry_run=False)

    assert result["dry_run"] is False
    verify = verify_install(root, home, platform_ids=["codex"])
    assert verify["ok"] is True
    assert all(adapter["is_portable_copy"] for adapter in verify["adapters"])
    assert verify["adapters"][0]["provenance_current"] == "repo-portable-copy"
    assert not (root / ".cursor" / "skills").exists()

    rolled = rollback(root, home)
    assert rolled["removed"]


def test_portable_adapter_digest_drift_is_reported(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"

    apply_plan(
        root,
        build_install_plan(root, home=home, packs=["core"], attach_mode="portable", platform_ids=["codex"]),
        home=home,
    )
    adapter = root / ".codex" / "skills"
    with (adapter / "ls-context" / "SKILL.md").open("a", encoding="utf-8") as handle:
        handle.write("\n# local portable drift\n")

    verify = verify_install(root, home, platform_ids=["codex"])

    assert verify["ok"] is False
    assert any("portable adapter package digest differs" in issue for issue in verify["issues"])
    assert "portable adapter package differs from global package: ls-context" in verify["provenance_warnings"]


def test_platform_selector_limits_adapters(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)

    plan = build_install_plan(root, home=home, packs=["core"], platform_ids=["codex"])
    result = apply_plan(root, plan, home=home, dry_run=False)

    assert result["dry_run"] is False
    assert_scoped_adapter(root / ".codex" / "skills", "ls-context")
    assert not (root / ".kilo" / "skills").exists()
    assert not (root / ".cursor" / "skills").exists()
    verify = verify_install(root, home, platform_ids=["codex"])
    assert verify["ok"] is True
    assert {adapter["platform"] for adapter in verify["adapters"]} == {"codex"}

    with pytest.raises(ValueError, match="platform-scoped rollback"):
        rollback(root, home, platform_ids=["codex"])


def test_multi_platform_selector_attaches_only_requested_adapters(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)

    plan = build_install_plan(root, home=home, packs=["core"], platform_ids=["codex", "kilo"])
    result = apply_plan(root, plan, home=home, dry_run=False)
    verify = verify_install(root, home)

    assert result["dry_run"] is False
    assert {Path(adapter["repo_path"]).parent.name for adapter in verify["adapters"]} == {".codex", ".kilo"}
    assert {adapter["platform"] for adapter in verify["adapters"]} == {"codex", "kilo"}
    assert_scoped_adapter(root / ".codex" / "skills", "ls-context")
    assert_scoped_adapter(root / ".kilo" / "skills", "ls-context")
    assert not (root / ".cursor" / "skills").exists()


def test_external_target_directory_attaches_selected_adapter(tmp_path: Path) -> None:
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
    assert_scoped_adapter(target / ".cursor" / "skills", "ls-context")
    assert not (root / ".cursor" / "skills").exists()
    assert verify["ok"] is True
    assert {adapter["platform"] for adapter in verify["adapters"]} == {"cursor"}
    assert lock["target_root"] == str(target)
    assert lock["platforms"] == ["cursor"]
    assert not (root / ".localsetup/lock.json").exists()


def test_external_target_install_verify_and_context_freshness_smoke(tmp_path: Path) -> None:
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
            str(root / "_localsetup" / "tools" / "localsetup.py"),
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
            str(root / "_localsetup" / "tools" / "localsetup.py"),
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


def test_verify_level_filesystem_and_trace_json(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "consumer"
    target.mkdir()
    plan = build_install_plan(root, home=home, packs=["core"], platform_ids=["codex"], target_root=target)
    apply_plan(root, plan, home=home, target_root=target)
    trace = tmp_path / "trace.jsonl"
    tool = root / "_localsetup" / "tools" / "localsetup.py"

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
            "filesystem",
            "--trace-json",
            str(trace),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["level"] == "filesystem"
    assert not any(row.get("status") == "not_run" for row in payload["rules"])
    trace_rows = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    assert trace_rows[-1]["event"] == "verify"


def test_verify_rejects_unimplemented_levels(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    tool = root / "_localsetup" / "tools" / "localsetup.py"

    for level in ("host", "smoke"):
        completed = subprocess.run(
            [
                sys.executable,
                str(tool),
                "--repo",
                str(root),
                "verify",
                "--tools",
                "codex",
                "--level",
                level,
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        assert completed.returncode != 0
        assert "invalid choice" in completed.stderr


def test_registry_refs_preserve_shared_packages_until_last_rollback(tmp_path: Path) -> None:
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


def test_narrowed_rerun_reconciles_registry_refs_and_prunes_packages(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"

    apply_plan(
        root,
        build_install_plan(root, home=home, global_packs=["dev"], repo_packs=["dev"], platform_ids=["codex"]),
        home=home,
    )
    dev_package = home / ".local/share/localsetup/packages/ls-nodejs-nextjs"
    assert dev_package.is_dir()

    apply_plan(
        root,
        build_install_plan(root, home=home, global_packs=["core"], repo_packs=["core"], platform_ids=["codex"]),
        home=home,
    )
    registry = load_json(home / ".local/share/localsetup/registry.json")
    target_id = str(root.resolve())

    assert "ls-nodejs-nextjs" not in registry["targets"][target_id]["packages"]
    assert "ls-nodejs-nextjs" not in registry["packages"]
    assert not dev_package.exists()

    rollback(root, home=home)
    assert not (home / ".local/share/localsetup/packages/ls-context").exists()


def test_provenance_report_cli_is_report_only(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    apply_plan(root, build_install_plan(root, home=home, packs=["core"], platform_ids=["codex"]), home=home)

    completed = subprocess.run(
        [
            sys.executable,
            "_localsetup/tools/localsetup.py",
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
    assert payload["adapters"][0]["provenance_current"] == "repo-scoped-symlink-adapter"


def test_provenance_report_global_shim_uses_caller_target(tmp_path: Path) -> None:
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
            str(root / "_localsetup/tools/localsetup.py"),
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


def test_detach_removes_adapters_and_preserves_packages(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    tool = root / "_localsetup" / "tools" / "localsetup.py"
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


def test_phase3_command_family_outputs_json(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "consumer"
    target.mkdir()
    (target / "package.json").write_text('{"scripts":{"test":"node --test"}}\n', encoding="utf-8")
    tool = root / "_localsetup" / "tools" / "localsetup.py"
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


def test_global_first_audit_reports_target_legacy_surfaces(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "consumer"
    stale_framework = target / "_localsetup"
    stale_framework.mkdir(parents=True)
    (target / "localsetup.lock.json").write_text('{"version": 1}\n', encoding="utf-8")
    tool = root / "_localsetup" / "tools" / "localsetup.py"

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


def test_policy_blocks_high_risk_skill_in_strict_mode(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    skill_md = root / "_localsetup" / "skills" / "ls-context" / "SKILL.md"
    skill_md.write_text(
        "---\nname: ls-context\ndescription: Context.\nrisk: high\npermissions: [filesystem-write]\n---\n",
        encoding="utf-8",
    )
    tool = root / "_localsetup" / "tools" / "localsetup.py"

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


def test_policy_blocks_invalid_risk_metadata_in_strict_mode(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    skill_md = root / "_localsetup" / "skills" / "ls-context" / "SKILL.md"
    skill_md.write_text(
        "---\nname: ls-context\ndescription: Context.\nrisk: critical\n---\n",
        encoding="utf-8",
    )
    tool = root / "_localsetup" / "tools" / "localsetup.py"

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


def test_sbom_command_writes_source_and_installed_boms(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    apply_plan(root, build_install_plan(root, home=home, packs=["core"]), home=home)
    tool = root / "_localsetup" / "tools" / "localsetup.py"
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
    shim_text = shim.read_text(encoding="utf-8")
    assert 'LOCALSETUP_PROJECT_PYTHON="$LOCALSETUP_SOURCE_ROOT/.venv/bin/python"' in shim_text
    assert '"$LOCALSETUP_PROJECT_PYTHON" "$LOCALSETUP_TOOL" --help' in shim_text
    assert 'exec "$LOCALSETUP_PROJECT_PYTHON"' in shim_text
    assert "no usable Python runtime for Localsetup" in shim_text
    assert "--sync-env --non-interactive --yes" in shim_text
    assert "uv --project" not in shim_text
    assert "run --locked" not in shim_text

    shim.write_text("#!/usr/bin/env bash\necho unmanaged\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unmanaged localsetup"):
        register_shell_command(root, home=home)


def test_shell_registration_requires_exact_managed_marker(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    shim = home / ".local" / "bin" / "localsetup"
    shim.parent.mkdir(parents=True)
    shim.write_text(
        "#!/usr/bin/env bash\n# managed_by=localsetup-extra\nexport LOCALSETUP_GLOBAL_SHIM=1\n",
        encoding="utf-8",
    )

    assert is_managed_shim(shim) is False
    with pytest.raises(RuntimeError, match="unmanaged localsetup"):
        register_shell_command(root, home=home, path_env=str(shim.parent))


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


def test_shell_registration_falls_back_when_project_python_is_bad(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    project_python = root / ".venv" / "bin" / "python"
    project_probe = tmp_path / "project-probe.txt"
    fallback_args = tmp_path / "fallback-args.txt"
    project_python.parent.mkdir(parents=True)
    project_python.write_text(
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" > {shlex.quote(str(project_probe))}\nexit 126\n",
        encoding="utf-8",
    )
    project_python.chmod(0o755)
    fallback_bin = tmp_path / "fallback-bin"
    fallback_bin.mkdir()
    fallback_python = fallback_bin / "python3"
    fallback_python.write_text(
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" > {shlex.quote(str(fallback_args))}\nexit 0\n",
        encoding="utf-8",
    )
    fallback_python.chmod(0o755)
    register_shell_command(root, home=home, path_env=str(home / ".local" / "bin"))

    completed = subprocess.run(
        [str(home / ".local" / "bin" / "localsetup"), "doctor"],
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PATH": f"{fallback_bin}{os.pathsep}/usr/bin:/bin"},
    )

    assert completed.returncode == 0
    project_probe_text = project_probe.read_text(encoding="utf-8")
    assert "_localsetup/tools/localsetup.py" in project_probe_text
    assert "--help" in project_probe_text
    fallback_text = fallback_args.read_text(encoding="utf-8")
    assert "_localsetup/tools/localsetup.py" in fallback_text
    assert "doctor" in fallback_text


def test_shell_registration_suppresses_project_python_import_traceback(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    project_python = root / ".venv" / "bin" / "python"
    project_probe = tmp_path / "project-probe.txt"
    fallback_args = tmp_path / "fallback-args.txt"
    project_python.parent.mkdir(parents=True)
    project_python.write_text(
        (
            "#!/usr/bin/env bash\n"
            f"printf '%s\\n' \"$*\" > {shlex.quote(str(project_probe))}\n"
            "echo 'Traceback: missing yaml in project venv' >&2\n"
            "exit 1\n"
        ),
        encoding="utf-8",
    )
    project_python.chmod(0o755)
    fallback_bin = tmp_path / "fallback-bin"
    fallback_bin.mkdir()
    fallback_python = fallback_bin / "python3"
    fallback_python.write_text(
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" > {shlex.quote(str(fallback_args))}\nexit 0\n",
        encoding="utf-8",
    )
    fallback_python.chmod(0o755)
    register_shell_command(root, home=home, path_env=str(home / ".local" / "bin"))

    completed = subprocess.run(
        [str(home / ".local" / "bin" / "localsetup"), "doctor"],
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PATH": f"{fallback_bin}{os.pathsep}/usr/bin:/bin"},
    )

    assert completed.returncode == 0
    assert "Traceback" not in completed.stderr
    assert "--help" in project_probe.read_text(encoding="utf-8")
    assert "doctor" in fallback_args.read_text(encoding="utf-8")


def test_shell_registration_reports_repair_when_no_python_runtime_works(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    project_python = root / ".venv" / "bin" / "python"
    project_python.parent.mkdir(parents=True)
    project_python.write_text("#!/usr/bin/env bash\nexit 126\n", encoding="utf-8")
    project_python.chmod(0o755)
    fallback_bin = tmp_path / "fallback-bin"
    fallback_bin.mkdir()
    fallback_python = fallback_bin / "python3"
    fallback_python.write_text(
        "#!/usr/bin/env bash\necho 'Traceback: missing yaml' >&2\nexit 1\n",
        encoding="utf-8",
    )
    fallback_python.chmod(0o755)
    register_shell_command(root, home=home, path_env=str(home / ".local" / "bin"))

    completed = subprocess.run(
        [str(home / ".local" / "bin" / "localsetup"), "doctor"],
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PATH": f"{fallback_bin}{os.pathsep}/usr/bin:/bin"},
    )

    assert completed.returncode == 2
    assert "no usable Python runtime for Localsetup" in completed.stderr
    assert "--sync-env --non-interactive --yes" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_shell_registration_reports_error_and_status_edge_cases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import _localsetup.core.shell as shell_mod

    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"

    with pytest.raises(FileNotFoundError, match="missing Localsetup source checkout"):
        register_shell_command(tmp_path / "missing-source", home=home)

    shim = home / ".local" / "bin" / "localsetup"
    register_shell_command(root, home=home, path_env=str(shim.parent))
    shim.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                f"# {shell_mod.SHIM_MARKER}",
                f"export {shell_mod.SHIM_ENV}=1",
                "LOCALSETUP_SOURCE_ROOT='unterminated",
            ]
        ),
        encoding="utf-8",
    )
    assert shell_mod._recorded_source_root(shim) == "'unterminated"

    original_read_text = Path.read_text

    def raise_for_shim(path: Path, *args: object, **kwargs: object) -> str:
        if path == shim:
            raise OSError("simulated unreadable shim")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", raise_for_shim)
    assert is_managed_shim(shim) is False
    monkeypatch.setattr(Path, "read_text", original_read_text)

    earlier = tmp_path / "earlier"
    earlier.mkdir()
    fake = earlier / "localsetup"
    fake.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake.chmod(0o755)
    status = shell_registration_status(root, home=home, path_env=f"{earlier}{os.pathsep}{shim.parent}")
    assert status["which"] == str(fake)
    assert any("before the managed shim" in warning for warning in status["warnings"])


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
    assert_scoped_adapter(target / ".codex" / "skills", "ls-context")


def test_cli_tools_and_yes_aliases_install(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    tool = root / "_localsetup" / "tools" / "localsetup.py"

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
    assert_scoped_adapter(root / ".codex" / "skills", "ls-context")


def test_global_shim_invocation_installs_at_detected_git_root(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target"
    nested = target / "nested" / "deeper"
    nested.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=target, text=True, capture_output=True, check=True)
    tool = root / "_localsetup" / "tools" / "localsetup.py"
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
    assert_scoped_adapter(target / ".codex" / "skills", "ls-context")
    assert (target / ".localsetup/lock.json").is_file()
    assert not (root / ".codex" / "skills").exists()


def test_apply_rejects_target_root_that_differs_from_plan(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target-repo"
    other = tmp_path / "other-target"
    target.mkdir()
    other.mkdir()

    plan = build_install_plan(root, home=home, packs=["core"], platform_ids=["cursor"], target_root=target)

    with pytest.raises(ValueError, match="target_root does not match install plan target_root"):
        apply_plan(root, plan, home=home, target_root=other)


def test_legacy_detection_uses_external_target_lockfile(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target-repo"
    target.mkdir()
    (root / "localsetup.lock.json").write_text('{"source": true}\n', encoding="utf-8")
    (target / "localsetup.lock.json").write_text('{"target": true}\n', encoding="utf-8")

    artifacts = detect_legacy_artifacts(root, home=home, target_root=target)
    lock_paths = [Path(item["path"]) for item in artifacts if item["kind"] == "lockfile"]

    assert lock_paths == [target / "localsetup.lock.json"]


def test_target_directory_without_selector_is_global_only(tmp_path: Path) -> None:
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


def test_install_migrates_legacy_root_lockfile(tmp_path: Path) -> None:
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


def test_target_templates_use_global_command_surface() -> None:
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
        "python3 _localsetup/tools/localsetup.py",
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


def test_preserves_existing_platform_config_when_attaching_skills(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    rules = root / ".cursor" / "rules"
    rules.mkdir(parents=True)
    (rules / "project.mdc").write_text("keep me\n", encoding="utf-8")

    plan = build_install_plan(root, home=home, packs=["core"], platform_ids=["cursor"])
    apply_plan(root, plan, home=home)

    assert_scoped_adapter(root / ".cursor" / "skills", "ls-context")
    assert (rules / "project.mdc").read_text(encoding="utf-8") == "keep me\n"


@pytest.mark.parametrize("collision_kind", ["directory", "file", "wrong_symlink", "dangling_symlink"])
def test_refuses_unmanaged_adapter_collisions(tmp_path: Path, collision_kind: str) -> None:
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


def test_rerun_with_correct_managed_symlink_is_idempotent(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"

    plan = build_install_plan(root, home=home, packs=["core"], platform_ids=["codex"])
    first = apply_plan(root, plan, home=home)
    second = apply_plan(root, plan, home=home)
    verify = verify_install(root, home)

    assert first["dry_run"] is False
    assert second["dry_run"] is False
    assert verify["ok"] is True
    assert_scoped_adapter(root / ".codex" / "skills", "ls-context")


def test_doctor_reports_selected_adapter_collisions_only(tmp_path: Path) -> None:
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


def test_rejects_unknown_platform_selectors(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)

    with pytest.raises(ValueError, match="unknown platform selector"):
        build_install_plan(root, home=home, packs=["core"], platform_ids=["typo"])
    with pytest.raises(ValueError, match="unknown platform selector"):
        verify_install(root, home, platform_ids=["typo"])
    with pytest.raises(ValueError, match="unknown platform selector"):
        rollback(root, home, platform_ids=["typo"])


def test_cli_csv_selector_normalization() -> None:
    assert _split_csv(["codex,kilo", "cursor"]) == ["codex", "kilo", "cursor"]
    assert _split_csv(None) is None


def test_config_file_and_cli_precedence(tmp_path: Path) -> None:
    config_path = tmp_path / "install.json"
    config_path.write_text(
        """{
  "platforms": ["codex"],
  "preset": "suggested",
  "packs": ["dev"],
  "skills": ["ls-context"],
  "skill_classes": ["operations"],
  "skill_tags": ["git"],
  "exclude_skills": ["ls-linux-patcher"],
  "global_packs": ["bootstrap"],
  "global_preset": "custom",
  "global_skills": ["ls-context"],
  "global_skill_classes": ["quality"],
  "global_skill_tags": ["testing"],
  "global_exclude_skills": ["ls-framework-audit"],
  "repo_packs": ["core"],
  "repo_preset": "core",
  "repo_skills": ["ls-test-runner"],
  "repo_skill_classes": ["development"],
  "repo_skill_tags": ["git"],
  "repo_exclude_skills": ["ls-linux-patcher"],
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
    merged = merge_cli_config(
        base,
        packs=["core"],
        preset="custom",
        skills=["ls-test-runner"],
        skill_classes=["quality"],
        skill_tags=["testing"],
        exclude_skills=["ls-context-index"],
        global_packs=["dev"],
        global_preset="suggested",
        repo_packs=["ops"],
        repo_preset="custom",
        attach_mode="symlink",
        dependency_mode="managed-venv",
    )

    assert base.platforms == ["codex"]
    assert base.preset == "suggested"
    assert base.packs == ["dev"]
    assert base.skills == ["ls-context"]
    assert base.skill_classes == ["operations"]
    assert base.skill_tags == ["git"]
    assert base.exclude_skills == ["ls-linux-patcher"]
    assert base.global_packs == ["bootstrap"]
    assert base.global_preset == "custom"
    assert base.global_skills == ["ls-context"]
    assert base.global_skill_classes == ["quality"]
    assert base.global_skill_tags == ["testing"]
    assert base.global_exclude_skills == ["ls-framework-audit"]
    assert base.repo_packs == ["core"]
    assert base.repo_preset == "core"
    assert base.repo_skills == ["ls-test-runner"]
    assert base.repo_skill_classes == ["development"]
    assert base.repo_skill_tags == ["git"]
    assert base.repo_exclude_skills == ["ls-linux-patcher"]
    assert base.attach_mode == "portable"
    assert base.target_directory == "/tmp/localsetup-target"
    assert base.data_root == "/tmp/localsetup-data"
    assert merged.packs == ["core"]
    assert merged.preset == "custom"
    assert merged.skills == ["ls-test-runner"]
    assert merged.skill_classes == ["quality"]
    assert merged.skill_tags == ["testing"]
    assert merged.exclude_skills == ["ls-context-index"]
    assert merged.global_packs == ["dev"]
    assert merged.global_preset == "suggested"
    assert merged.global_skills == ["ls-context"]
    assert merged.global_skill_classes == ["quality"]
    assert merged.global_skill_tags == ["testing"]
    assert merged.global_exclude_skills == ["ls-framework-audit"]
    assert merged.repo_packs == ["ops"]
    assert merged.repo_preset == "custom"
    assert merged.repo_skills == ["ls-test-runner"]
    assert merged.repo_skill_classes == ["development"]
    assert merged.repo_skill_tags == ["git"]
    assert merged.repo_exclude_skills == ["ls-linux-patcher"]
    assert merged.attach_mode == "symlink"
    assert merged.target_directory == "/tmp/localsetup-target"
    assert merged.data_root == "/tmp/localsetup-data"
    assert merged.dependency_mode == "uv-sync"


def test_schema_validation_is_optional_without_jsonschema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    schema = tmp_path / "schema.json"
    schema.write_text(
        json.dumps({"$schema": "https://json-schema.org/draft/2020-12/schema", "required": ["name"]}),
        encoding="utf-8",
    )
    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "jsonschema" or name.startswith("jsonschema."):
            raise ImportError("simulated missing jsonschema")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    assert validate_json_schema({}, schema, label="example", required=False) == []
    assert validate_json_schema({}, schema, label="example") == ["jsonschema is required to validate example"]


def test_manifest_loader_reports_invalid_shapes(tmp_path: Path) -> None:
    from _localsetup.core.manifests import ManifestError, load_pack_config, load_platforms, validate_manifest_schemas

    root = tmp_path / "repo"
    config = root / "_localsetup" / "config"
    config.mkdir(parents=True)

    assert "pack.yaml schema validation failed: missing manifest" in validate_manifest_schemas(root)[0]

    (config / "pack.yaml").write_text("[]\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="manifest is not a mapping"):
        load_pack_config(root)

    valid_base = {
        "pack_id": "localsetup",
        "namespace": "ls",
        "packs": {},
        "workflow_packs": {},
    }
    (config / "pack.yaml").write_text(json.dumps({**valid_base, "extensions": []}), encoding="utf-8")
    with pytest.raises(ManifestError, match="extensions must be a mapping"):
        load_pack_config(root)

    (config / "pack.yaml").write_text(
        json.dumps({**valid_base, "extensions": {"skill_taxonomy": []}}),
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match="extensions.skill_taxonomy must be a mapping"):
        load_pack_config(root)

    (config / "pack.yaml").write_text(
        json.dumps({**valid_base, "extensions": {"skill_taxonomy": {"ls-context": []}}}),
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match="extensions.skill_taxonomy.ls-context must be a mapping"):
        load_pack_config(root)

    (config / "platforms.yaml").write_text(json.dumps({"platforms": {}}), encoding="utf-8")
    with pytest.raises(ManifestError, match="platforms must be a list"):
        load_platforms(root)


def test_doctor_reports_manifest_and_environment_blockers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import _localsetup.core.doctor as doctor_mod

    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target"
    target.mkdir()

    monkeypatch.setattr(doctor_mod.platform, "system", lambda: "Windows")
    monkeypatch.setattr(doctor_mod, "load_pack_config", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    manifest_failure = run_doctor(root, home=home)
    assert manifest_failure["ok"] is False
    assert "native Windows is unsupported" in manifest_failure["blockers"][0]
    assert any("manifest validation failed: boom" in blocker for blocker in manifest_failure["blockers"])

    fake_pack = SimpleNamespace(
        pack_id="localsetup",
        global_root="~/.local/share/localsetup/packages",
        global_registry="~/.local/share/localsetup/registry.json",
    )
    fake_platform = SimpleNamespace(platform_id="codex")
    monkeypatch.setattr(doctor_mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(doctor_mod, "load_pack_config", lambda *args, **kwargs: fake_pack)
    monkeypatch.setattr(doctor_mod, "load_platforms", lambda *args, **kwargs: [fake_platform])
    monkeypatch.setattr(doctor_mod, "validate_skill_catalog", lambda *args, **kwargs: ["bad skill"])
    monkeypatch.setattr(doctor_mod, "validate_workflow_catalog", lambda *args, **kwargs: ["bad workflow"])
    monkeypatch.setattr(doctor_mod, "tool_status", lambda name: {"name": name, "ok": False})
    monkeypatch.setattr(
        doctor_mod,
        "dependency_status",
        lambda *args, **kwargs: SimpleNamespace(
            to_dict=lambda: {
                "mode": "uv-sync",
                "warnings": ["dependency warning"],
                "blockers": ["dependency blocker"],
            }
        ),
    )
    monkeypatch.setattr(
        doctor_mod,
        "adapter_status",
        lambda *args, **kwargs: [
            {
                "platform": "codex",
                "repo_path": str(target / ".codex" / "skills"),
                "collision_reason": "regular file",
                "package_integrity_failures": [{"package": "ls-context"}],
            }
        ],
    )
    monkeypatch.setattr(doctor_mod, "adapter_targets", lambda *args, **kwargs: [{"repo_path": target / ".codex" / "skills"}])
    monkeypatch.setattr(doctor_mod, "_writable_status", lambda path: {"path": str(path), "nearest_existing": str(path), "ok": False})
    monkeypatch.setattr(doctor_mod, "detect_legacy_artifacts", lambda *args, **kwargs: [{"kind": "legacy"}])
    monkeypatch.setattr(doctor_mod, "scan_legacy_references", lambda *args, **kwargs: [])
    monkeypatch.setattr(doctor_mod, "provenance_report", lambda *args, **kwargs: {"warnings": ["prov"], "repair_hints": ["hint"]})
    monkeypatch.setattr(doctor_mod, "install_inventory", lambda *args, **kwargs: {"inventory": []})

    result = run_doctor(root, home=home, platform_ids=["codex"], target_root=target)

    assert result["ok"] is False
    assert any("skill catalog: bad skill" in blocker for blocker in result["blockers"])
    assert any("workflow catalog: bad workflow" in blocker for blocker in result["blockers"])
    assert "missing required tool: git" in result["blockers"]
    assert "missing recommended tool: rg" in result["warnings"]
    assert "dependency blocker" in result["blockers"]
    assert "dependency warning" in result["warnings"]
    assert any("adapter collision (regular file)" in blocker for blocker in result["blockers"])
    assert any("adapter package target mismatch (ls-context)" in blocker for blocker in result["blockers"])
    assert any("path is not writable" in blocker for blocker in result["blockers"])
    assert any("legacy artifacts detected" in warning for warning in result["warnings"])


def test_cli_install_passes_configured_data_root_to_uv_sync(
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
        target_root: Path | None = None,
        runner: object | None = None,
    ) -> dict:
        captured.append(data_root)
        assert repo_root == root
        assert mode == "uv-sync"
        assert data_root is not None
        interpreter = root / ".venv" / "bin" / "python"
        return {
            "mode": mode,
            "interpreter": str(interpreter),
            "dependency_manager": "uv",
            "project_root": str(root),
            "pyproject": str(root / "pyproject.toml"),
            "lockfile": str(root / "uv.lock"),
            "environment_path": str(root / ".venv"),
            "lock": {"dependency_manager": "uv", "lock_status": "current"},
            "changed": False,
            "warnings": [],
            "blockers": [],
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
    assert lock["python_interpreter"] == str(root / ".venv" / "bin" / "python")
    assert lock["dependency_state"]["dependency_manager"] == "uv"


def test_uv_sync_commands_and_lock_interpreter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    monkeypatch.setenv("LOCALSETUP_UV_BIN", "uv")
    commands: list[list[str]] = []

    def fake_runner(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        commands.append(cmd)
        if cmd[-1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="uv 0.11.5\n", stderr="")
        if "sync" in cmd:
            python_path = root / ".venv" / "bin" / "python"
            python_path.parent.mkdir(parents=True, exist_ok=True)
            python_path.write_text("# fake python\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    deps = ensure_dependencies(root, mode="managed-venv", data_root=home / ".local/share/localsetup", runner=fake_runner)
    plan = build_install_plan(root, home=home, packs=["core"], platform_ids=["codex"])
    result = apply_plan(root, plan, home=home, dependency_info=deps)
    lock = load_json(root / ".localsetup/lock.json")

    assert any(cmd[-2:] == ["lock", "--check"] for cmd in commands)
    assert any("sync" in cmd and "--locked" in cmd and "--no-dev" in cmd for cmd in commands)
    assert deps["mode"] == "uv-sync"
    assert deps["interpreter"].endswith(".venv/bin/python")
    assert deps["lock"]["dependency_manager"] == "uv"
    assert deps["lock"]["lock_status"] == "current"
    assert lock["python_interpreter"] == deps["interpreter"]
    assert lock["dependency_state"]["dependency_manager"] == "uv"
    assert result["lockfile"].endswith(".localsetup/lock.json")


def test_uv_prompt_only_reports_lock_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_temp_repo(tmp_path)
    monkeypatch.setenv("LOCALSETUP_UV_BIN", "uv")

    def fake_runner(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if cmd[-1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="uv 0.11.5\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    deps = ensure_dependencies(root, mode="prompt-only", runner=fake_runner)

    assert deps["changed"] is False
    assert deps["lock_status"] == "current"
    assert deps["lock"]["dependency_manager"] == "uv"


def test_doctor_reports_corrupt_legacy_global_venv_without_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import _localsetup.core.dependencies as deps_mod
    import _localsetup.core.doctor as doctor_mod

    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    data_root = home / ".local" / "share" / "localsetup"
    legacy_python = data_root / "venv" / "bin" / "python"
    legacy_python.parent.mkdir(parents=True)
    legacy_python.write_text("# fake python\n", encoding="utf-8")
    legacy_python.chmod(0o644)

    def fake_runner(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if cmd[-1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="uv 0.11.5\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setenv("LOCALSETUP_UV_BIN", "uv")
    monkeypatch.setattr(
        doctor_mod,
        "dependency_status",
        lambda repo_root, **kwargs: deps_mod.dependency_status(repo_root, runner=fake_runner, **kwargs),
    )

    prompt_only = run_doctor(root, home=home, dependency_mode="prompt-only", data_root=data_root)
    default_mode = run_doctor(root, home=home, data_root=data_root)

    for result in (prompt_only, default_mode):
        assert result["dependencies"]["mode"] == "prompt-only"
        assert result["dependencies"]["blockers"] == []
        assert not any("Permission denied" in blocker for blocker in result["blockers"])
        assert any("legacy global venv interpreter is not executable" in warning for warning in result["warnings"])
        legacy_environment = result["dependencies"]["legacy_environment"]
        assert legacy_environment["ignored"] is True
        assert legacy_environment["ok"] is False
        assert legacy_environment["interpreter"] == str(legacy_python)
        assert any("Remove or quarantine" in step for step in result["dependencies"]["recoverable_next_steps"])
    assert legacy_python.read_text(encoding="utf-8") == "# fake python\n"


def test_uv_already_synced_skips_nested_sync(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_temp_repo(tmp_path)
    monkeypatch.setenv("LOCALSETUP_UV_BIN", "uv")
    monkeypatch.setenv("LOCALSETUP_UV_ALREADY_SYNCED", "1")
    commands: list[list[str]] = []

    def fake_runner(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        commands.append(cmd)
        if cmd[-1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="uv 0.11.5\n", stderr="")
        assert "sync" not in cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    deps = ensure_dependencies(root, mode="uv-sync", runner=fake_runner)

    assert deps["sync_status"] == "success"
    assert deps["changed"] is False
    assert any(cmd[-2:] == ["lock", "--check"] for cmd in commands)
    assert not any("sync" in cmd for cmd in commands)


def test_uv_sync_quarantines_corrupt_source_venv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_temp_repo(tmp_path)
    broken_python = root / ".venv" / "bin" / "python"
    broken_python.parent.mkdir(parents=True)
    broken_python.write_text("# fake python\n", encoding="utf-8")
    broken_python.chmod(0o644)
    monkeypatch.setenv("LOCALSETUP_UV_BIN", "uv")

    def fake_runner(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if cmd[-1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="uv 0.11.5\n", stderr="")
        if "sync" in cmd:
            python_path = root / ".venv" / "bin" / "python"
            python_path.parent.mkdir(parents=True, exist_ok=True)
            python_path.write_text("# rebuilt python\n", encoding="utf-8")
            python_path.chmod(0o755)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    deps = ensure_dependencies(root, mode="uv-sync", runner=fake_runner)

    quarantined = deps["quarantined_environments"]
    assert deps["repair_attempted"] is True
    assert len(quarantined) == 1
    assert quarantined[0]["owner"] == "source_venv"
    assert Path(quarantined[0]["quarantine_path"]).is_dir()
    assert Path(quarantined[0]["record_path"]).is_file()
    assert broken_python.read_text(encoding="utf-8") == "# rebuilt python\n"
    assert deps["sync_attempts"] == 1


def test_uv_sync_retries_source_venv_corruption_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_temp_repo(tmp_path)
    python_path = root / ".venv" / "bin" / "python"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("# healthy before uv failure\n", encoding="utf-8")
    python_path.chmod(0o755)
    (root / ".venv" / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    monkeypatch.setenv("LOCALSETUP_UV_BIN", "uv")
    sync_calls = 0

    def fake_runner(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        nonlocal sync_calls
        if cmd[-1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="uv 0.11.5\n", stderr="")
        if "sync" in cmd:
            sync_calls += 1
            if sync_calls == 1:
                return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="failed to read .venv/pyvenv.cfg")
            rebuilt = root / ".venv" / "bin" / "python"
            rebuilt.parent.mkdir(parents=True, exist_ok=True)
            rebuilt.write_text("# rebuilt after retry\n", encoding="utf-8")
            rebuilt.chmod(0o755)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    deps = ensure_dependencies(root, mode="uv-sync", runner=fake_runner)

    assert deps["sync_attempts"] == 2
    assert sync_calls == 2
    assert deps["quarantined_environments"][0]["uv_error"] == "failed to read .venv/pyvenv.cfg"
    assert python_path.read_text(encoding="utf-8") == "# rebuilt after retry\n"


def test_uv_sync_repairs_legacy_envs_without_touching_target_venv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "project"
    data_root = home / ".local" / "share" / "localsetup"
    legacy_global = data_root / "venv" / "bin" / "python"
    legacy_target = target / ".localsetup" / "venv" / "bin" / "python"
    project_python = target / ".venv" / "bin" / "python"
    for path in (legacy_global, legacy_target, project_python):
        path.parent.mkdir(parents=True)
        path.write_text("# fake python\n", encoding="utf-8")
        path.chmod(0o644)
    monkeypatch.setenv("LOCALSETUP_UV_BIN", "uv")

    def fake_runner(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if cmd[-1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="uv 0.11.5\n", stderr="")
        if "sync" in cmd:
            rebuilt = root / ".venv" / "bin" / "python"
            rebuilt.parent.mkdir(parents=True, exist_ok=True)
            rebuilt.write_text("# rebuilt python\n", encoding="utf-8")
            rebuilt.chmod(0o755)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    deps = ensure_dependencies(root, mode="uv-sync", data_root=data_root, target_root=target, runner=fake_runner)

    owners = {item["owner"] for item in deps["quarantined_environments"]}
    assert owners == {"legacy_global_venv", "legacy_target_local_venv"}
    assert not (data_root / "venv").exists()
    assert not (target / ".localsetup" / "venv").exists()
    assert project_python.exists()
    assert project_python.read_text(encoding="utf-8") == "# fake python\n"


def test_uv_sync_leaves_healthy_source_venv_in_place(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_temp_repo(tmp_path)
    python_path = root / ".venv" / "bin" / "python"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("# healthy python\n", encoding="utf-8")
    python_path.chmod(0o755)
    (root / ".venv" / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    monkeypatch.setenv("LOCALSETUP_UV_BIN", "uv")

    def fake_runner(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if cmd[-1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="uv 0.11.5\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    deps = ensure_dependencies(root, mode="uv-sync", runner=fake_runner)

    assert deps["repair_attempted"] is False
    assert deps["quarantined_environments"] == []
    assert python_path.read_text(encoding="utf-8") == "# healthy python\n"


def test_uv_sync_quarantine_failure_blocks_without_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from _localsetup.core import dependencies as deps_mod

    root = make_temp_repo(tmp_path)
    broken_python = root / ".venv" / "bin" / "python"
    broken_python.parent.mkdir(parents=True)
    broken_python.write_text("# fake python\n", encoding="utf-8")
    broken_python.chmod(0o644)
    original_rename = Path.rename

    def failing_rename(self: Path, target: Path) -> Path:
        if self == root / ".venv":
            raise OSError("simulated rename failure")
        return original_rename(self, target)

    monkeypatch.setenv("LOCALSETUP_UV_BIN", "uv")
    monkeypatch.setattr(deps_mod.Path, "rename", failing_rename)

    def fake_runner(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if cmd[-1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="uv 0.11.5\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    with pytest.raises(RuntimeError, match="failed to quarantine Localsetup-owned environment"):
        ensure_dependencies(root, mode="uv-sync", runner=fake_runner)
    assert broken_python.exists()


def test_uv_sync_failure_preserves_quarantine_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_temp_repo(tmp_path)
    broken_python = root / ".venv" / "bin" / "python"
    broken_python.parent.mkdir(parents=True)
    broken_python.write_text("# fake python\n", encoding="utf-8")
    broken_python.chmod(0o644)
    monkeypatch.setenv("LOCALSETUP_UV_BIN", "uv")

    def fake_runner(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if cmd[-1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="uv 0.11.5\n", stderr="")
        if "sync" in cmd:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="offline cache miss")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    with pytest.raises(RuntimeError, match="offline-cache-miss"):
        ensure_dependencies(root, mode="uv-sync", runner=fake_runner)
    assert list((root / ".localsetup" / "state" / "dependency-repair").glob(".venv-*.json"))


def test_uv_stale_lock_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_temp_repo(tmp_path)
    monkeypatch.setenv("LOCALSETUP_UV_BIN", "uv")

    def fake_runner(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if cmd[-1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="uv 0.11.5\n", stderr="")
        if cmd[-2:] == ["lock", "--check"]:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="lock would change")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with pytest.raises(RuntimeError, match="uv lockfile is stale"):
        ensure_dependencies(root, mode="uv-sync", runner=fake_runner)


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


def test_agent_context_and_markdown_report(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    config = InstallConfig(platforms=["codex"], packs=["core"], dependency_mode="prompt-only")

    context = build_agent_context(root, home=home, config=config)
    markdown = render_markdown_report(context)

    assert {"environment", "selected_platforms", "dependencies", "migration", "actions", "blockers", "warnings", "commands", "rollback", "verification"} <= set(context)
    assert context["selected_platforms"] == ["codex"]
    assert context["selected_packs"] == ["core"]
    assert "# Localsetup Install Context" in markdown
    assert "localsetup verify --platforms codex" in markdown
    assert "python3 _localsetup/tools/localsetup.py verify" not in markdown


def test_cli_doctor_target_warning_requires_explicit_target(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target-repo"
    target.mkdir()
    tool = root / "_localsetup" / "tools" / "localsetup.py"

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


def test_cli_context_target_warning_requires_explicit_target(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target-repo"
    target.mkdir()
    tool = root / "_localsetup" / "tools" / "localsetup.py"

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


def test_self_refresh_defaults_to_all_packs_and_existing_repo_adapters(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    tool = root / "_localsetup" / "tools" / "localsetup.py"

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
    assert_scoped_adapter(root / ".codex" / "skills", "ls-context")
    assert payload["verify"]["adapters"][0]["is_scoped_symlink_adapter"] is True
    assert (root / ".cursor" / "skills").resolve() == external_global


def test_self_refresh_preserves_existing_portable_adapter_mode(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    tool = root / "_localsetup" / "tools" / "localsetup.py"

    portable_adapter = root / ".codex" / "skills"
    portable_adapter.mkdir(parents=True, exist_ok=True)
    (portable_adapter / ".localsetup-portable").write_text("managed_by=localsetup\n", encoding="utf-8")

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
    overview = (root / "_localsetup" / "docs" / "migration" / "overview.md").read_text(encoding="utf-8")

    assert "install --mode portable --apply" not in overview
    assert "install --mode portable --platforms codex --apply" in overview


def test_docs_and_package(tmp_path: Path) -> None:
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

    artifact = tmp_path / "localsetup-public.tar.gz"
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
        "assets/localsetup-readme-hero.svg",
        "assets/localsetup-architecture.svg",
        "assets/localsetup-install-lifecycle.svg",
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
    artifact = tmp_path / "missing" / "nested" / "localsetup-public.tar.gz"

    package = build_public_artifact(root, artifact)

    assert artifact.is_file()
    assert Path(package["sha256"]).is_file()
    assert Path(package["sbom"]).is_file()


def test_package_command_fails_when_leak_scan_finds_private_file(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    tool = root / "_localsetup" / "tools" / "localsetup.py"
    leak = root / "_localsetup" / "token.secret"
    leak.write_text("do not ship\n", encoding="utf-8")
    artifact = tmp_path / "localsetup-public.tar.gz"

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
    artifact = tmp_path / "localsetup-public.tar.gz"
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
    artifact = tmp_path / "localsetup-public.tar.gz"
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
    taxonomy_by_script = json.loads(
        (root / "_localsetup/docs/_generated/skill-taxonomy.json").read_text(encoding="utf-8")
    )

    generate_alias_outputs(root)
    generated_by_v3_docs = json.loads(
        (root / "_localsetup/docs/_generated/workflow-catalog.json").read_text(encoding="utf-8")
    )
    taxonomy_by_v3_docs = json.loads(
        (root / "_localsetup/docs/_generated/skill-taxonomy.json").read_text(encoding="utf-8")
    )

    generated_by_script.pop("provenance", None)
    generated_by_v3_docs.pop("provenance", None)
    taxonomy_by_script.pop("provenance", None)
    taxonomy_by_v3_docs.pop("provenance", None)
    assert generated_by_script == workflow_catalog_payload(root)
    assert generated_by_v3_docs == workflow_catalog_payload(root)
    assert taxonomy_by_script == skill_taxonomy_payload(root)
    assert taxonomy_by_v3_docs == skill_taxonomy_payload(root)


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
    assert_scoped_adapter(root / ".codex" / "skills", "ls-context")
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
    assert_scoped_adapter(target / ".cursor" / "skills", "ls-context")
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
    marker = repo / "_localsetup" / "README.md"
    marker.parent.mkdir(parents=True)
    marker.write_text("# Localsetup\n", encoding="utf-8")
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


def make_bootstrap_git_repo_with_release_tags(tmp_path: Path) -> tuple[Path, str, str]:
    repo = make_bootstrap_git_repo(tmp_path)
    subprocess.run(["git", "tag", "v4.8.7"], cwd=repo, text=True, capture_output=True, check=True)
    (repo / "README.md").write_text("# Localsetup\n\nrelease refresh\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, text=True, capture_output=True, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Localsetup Test", "-c", "user.email=test@example.invalid", "commit", "-m", "release"],
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
    subprocess.run(["git", "tag", "v4.8.9"], cwd=repo, text=True, capture_output=True, check=True)
    subprocess.run(["git", "tag", "v4.9.0-rc.1"], cwd=repo, text=True, capture_output=True, check=True)
    old_commit = subprocess.run(
        ["git", "rev-list", "-n", "1", "v4.8.7"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    return repo, old_commit, current_commit


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
    effective_env = {
        **os.environ,
        "LOCALSETUP_WIZARD_SELECTION_MODE": "line",
        "LOCALSETUP_WIZARD_DETAIL": "compact",
        **(env or {}),
    }
    return subprocess.run(
        [script, "-q", "-e", "-c", shell_command, str(log_path)],
        input=input_text,
        cwd=cwd,
        env=effective_env,
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


def test_root_installer_sync_env_rejects_old_uv_before_sync(tmp_path: Path) -> None:
    install_path = Path(__file__).resolve().parents[2] / "install"
    fake_uv = tmp_path / "uv"
    sync_marker = tmp_path / "sync-called"
    fake_uv.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"$1\" == \"--version\" ]]; then echo 'uv 0.4.26'; exit 0; fi\n"
        f"if [[ \"$*\" == *sync* ]]; then touch {shlex.quote(str(sync_marker))}; fi\n"
        "exit 99\n",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)

    completed = subprocess.run(
        [
            str(install_path),
            "--directory",
            str(Path(__file__).resolve().parents[2]),
            "--tools",
            "codex",
            "--sync-env",
            "--non-interactive",
            "--yes",
            "--home",
            str(tmp_path / "home"),
            "--target-directory",
            str(tmp_path / "target"),
        ],
        env={**os.environ, "LOCALSETUP_UV_BIN": str(fake_uv)},
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "uv 0.4.26 is too old; Localsetup requires uv >= 0.4.27" in completed.stderr
    assert not sync_marker.exists()


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
    assert (managed_source / "_localsetup/tools/localsetup.py").is_file()
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


def test_root_installer_discovers_latest_stable_release_tag_for_managed_source(tmp_path: Path) -> None:
    install_path = Path(__file__).resolve().parents[2] / "install"
    bootstrap_repo, old_commit, current_commit = make_bootstrap_git_repo_with_release_tags(tmp_path / "bootstrap")
    outside = tmp_path / "outside"
    home = tmp_path / "home"
    managed_source = tmp_path / "managed-source"
    outside.mkdir()
    subprocess.run(["git", "clone", str(bootstrap_repo), str(managed_source)], text=True, capture_output=True, check=True)
    subprocess.run(["git", "checkout", "--detach", old_commit], cwd=managed_source, text=True, capture_output=True, check=True)
    env = {
        **os.environ,
        "LOCALSETUP_BOOTSTRAP_REPO": str(bootstrap_repo),
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
    assert (managed_source / "README.md").read_text(encoding="utf-8") == "# Localsetup\n\nrelease refresh\n"
    assert (home / ".local/share/localsetup/packages/ls-context").is_dir()


def test_root_installer_filters_github_release_api_payload_before_tag_fallback(tmp_path: Path) -> None:
    install_path = Path(__file__).resolve().parents[2] / "install"
    bootstrap_repo, _old_commit, current_commit = make_bootstrap_git_repo_with_release_tags(tmp_path / "bootstrap")
    outside = tmp_path / "outside"
    home = tmp_path / "home"
    managed_source = tmp_path / "managed-source"
    releases = tmp_path / "releases.json"
    outside.mkdir()
    releases.write_text(
        json.dumps(
            [
                {
                    "tag_name": "v4.9.0-rc.1",
                    "draft": False,
                    "prerelease": True,
                    "published_at": "2026-05-20T00:00:00Z",
                },
                {
                    "tag_name": "v4.8.10",
                    "draft": True,
                    "prerelease": False,
                    "published_at": "2026-05-19T03:00:00Z",
                },
                {
                    "tag_name": "v4.8.9",
                    "draft": False,
                    "prerelease": False,
                    "published_at": "2026-05-19T02:00:00Z",
                },
                {
                    "tag_name": "v4.8.7",
                    "draft": False,
                    "prerelease": False,
                    "published_at": "2026-05-18T02:00:00Z",
                },
            ]
        ),
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "LOCALSETUP_BOOTSTRAP_REPO": str(bootstrap_repo),
        "LOCALSETUP_BOOTSTRAP_RELEASES_URL": releases.resolve().as_uri(),
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

    checked_out = subprocess.run(
        ["git", "-C", str(managed_source), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    assert completed.returncode == 0, completed.stderr
    assert checked_out == current_commit


def test_root_installer_bootstrap_ref_override_skips_latest_release_discovery(tmp_path: Path) -> None:
    install_path = Path(__file__).resolve().parents[2] / "install"
    bootstrap_repo, old_commit, _current_commit = make_bootstrap_git_repo_with_release_tags(tmp_path / "bootstrap")
    outside = tmp_path / "outside"
    home = tmp_path / "home"
    managed_source = tmp_path / "managed-source"
    outside.mkdir()
    env = {
        **os.environ,
        "LOCALSETUP_BOOTSTRAP_REPO": str(bootstrap_repo),
        "LOCALSETUP_BOOTSTRAP_REF": "v4.8.7",
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

    checked_out = subprocess.run(
        ["git", "-C", str(managed_source), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    assert completed.returncode == 0, completed.stderr
    assert checked_out == old_commit
    assert (managed_source / "README.md").read_text(encoding="utf-8") == "# Localsetup\n"


def test_root_installer_offline_release_lookup_reuses_existing_managed_source(tmp_path: Path) -> None:
    install_path = Path(__file__).resolve().parents[2] / "install"
    bootstrap_repo = make_bootstrap_git_repo(tmp_path / "bootstrap")
    outside = tmp_path / "outside"
    home = tmp_path / "home"
    managed_source = tmp_path / "managed-source"
    outside.mkdir()
    subprocess.run(["git", "clone", str(bootstrap_repo), str(managed_source)], text=True, capture_output=True, check=True)
    before = subprocess.run(
        ["git", "-C", str(managed_source), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    env = {
        **os.environ,
        "LOCALSETUP_BOOTSTRAP_REPO": str(tmp_path / "missing-remote"),
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

    after = subprocess.run(
        ["git", "-C", str(managed_source), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    assert completed.returncode == 0, completed.stderr
    assert "failed to discover the latest Localsetup release; using existing managed source" in completed.stderr
    assert after == before
    assert (home / ".local/share/localsetup/packages/ls-context").is_dir()


def test_root_installer_offline_release_lookup_without_managed_source_fails_actionably(tmp_path: Path) -> None:
    install_path = Path(__file__).resolve().parents[2] / "install"
    outside = tmp_path / "outside"
    managed_source = tmp_path / "managed-source"
    outside.mkdir()
    env = {
        **os.environ,
        "LOCALSETUP_BOOTSTRAP_REPO": str(tmp_path / "missing-remote"),
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
    assert "failed to discover the latest Localsetup release and no managed source exists" in completed.stderr
    assert "LOCALSETUP_BOOTSTRAP_REF" in completed.stderr
    assert not managed_source.exists()


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
    (managed_source / "_localsetup" / "tools" / "localsetup.py").write_text("print('stale')\n", encoding="utf-8")
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
    assert "managed bootstrap source exists but is not a Localsetup checkout" in completed.stderr
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
    assert_scoped_adapter(target / ".codex" / "skills", "ls-context")
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
        input_text="\n\n\n\n\nyes\n",
        cwd=tmp_path,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert_scoped_adapter(target / ".cursor" / "skills", "ls-context")
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
        input_text="\n\n\n\nyes\n",
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
    term.diagnostic_command(["python3", "/tmp/" + "nested/" * 12 + "localsetup.py", "doctor"])

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


def test_wizard_checkbox_falls_back_to_line_mode_for_scripted_streams() -> None:
    term = TerminalWizard(
        input_stream=io.StringIO("1,2\n"),
        output_stream=io.StringIO(),
        color=False,
    )

    assert choose_many_checkbox(
        term,
        "Skills",
        [("ls-context", "ls-context"), ("ls-test-runner", "ls-test-runner")],
        default=["ls-context"],
    ) == ["ls-context", "ls-test-runner"]


@pytest.mark.parametrize(
    ("input_text", "expected"),
    [
        ("\x1b[A", "up"),
        ("\x1b[B", "down"),
        ("\x1bOA", "up"),
        ("\x1bOB", "down"),
        ("\x1b[1;5A", "up"),
        ("\x1b[1;5B", "down"),
    ],
)
def test_wizard_read_key_recognizes_arrow_sequences(
    monkeypatch: pytest.MonkeyPatch, input_text: str, expected: str
) -> None:
    key_input = FakeKeyInput(input_text)
    patch_fake_key_input(monkeypatch, key_input)
    term = TerminalWizard(input_stream=key_input, output_stream=io.StringIO(), color=False)

    assert wizard._read_key(term) == expected


@pytest.mark.parametrize("input_text", ["\x1b", "\x1b[", "\x1b[1;5", "\x1bOC"])
def test_wizard_read_key_treats_incomplete_or_unsupported_escape_as_unknown(
    monkeypatch: pytest.MonkeyPatch, input_text: str
) -> None:
    key_input = FakeKeyInput(input_text)
    patch_fake_key_input(monkeypatch, key_input)
    term = TerminalWizard(input_stream=key_input, output_stream=io.StringIO(), color=False)

    assert wizard._read_key(term) == "unknown"


def test_wizard_read_key_recognizes_ctrl_c() -> None:
    key_input = FakeKeyInput("\x03")
    term = TerminalWizard(input_stream=key_input, output_stream=io.StringIO(), color=False)

    assert wizard._read_key(term) == "ctrl-c"


def test_wizard_checkbox_unknown_printable_key_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    key_input = FakeKeyInput("x\n")
    enable_checkbox_key_mode(monkeypatch, key_input)
    term = TerminalWizard(input_stream=key_input, output_stream=io.StringIO(), color=False)

    assert choose_many_checkbox(
        term,
        "Skills",
        [("ls-context", "ls-context"), ("ls-test-runner", "ls-test-runner")],
        default=["ls-context"],
    ) == ["ls-context"]


def test_wizard_checkbox_application_cursor_arrows_move_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    key_input = FakeKeyInput("\x1bOB\x1bOA \n")
    enable_checkbox_key_mode(monkeypatch, key_input)
    term = TerminalWizard(input_stream=key_input, output_stream=io.StringIO(), color=False)

    assert choose_many_checkbox(
        term,
        "Skills",
        [("ls-context", "ls-context"), ("ls-test-runner", "ls-test-runner")],
        default=[],
    ) == ["ls-context"]


def test_wizard_checkbox_application_cursor_down_selects_next_item(monkeypatch: pytest.MonkeyPatch) -> None:
    key_input = FakeKeyInput("\x1bOB \n")
    enable_checkbox_key_mode(monkeypatch, key_input)
    term = TerminalWizard(input_stream=key_input, output_stream=io.StringIO(), color=False)

    assert choose_many_checkbox(
        term,
        "Skills",
        [("ls-context", "ls-context"), ("ls-test-runner", "ls-test-runner")],
        default=[],
    ) == ["ls-test-runner"]


def test_wizard_checkbox_q_still_cancels(monkeypatch: pytest.MonkeyPatch) -> None:
    key_input = FakeKeyInput("q")
    enable_checkbox_key_mode(monkeypatch, key_input)
    term = TerminalWizard(input_stream=key_input, output_stream=io.StringIO(), color=False)

    assert (
        choose_many_checkbox(term, "Skills", [("ls-context", "ls-context")], default=["ls-context"])
        == wizard.CANCEL
    )


def test_wizard_checkbox_ctrl_c_cancels(monkeypatch: pytest.MonkeyPatch) -> None:
    key_input = FakeKeyInput("\x03")
    enable_checkbox_key_mode(monkeypatch, key_input)
    term = TerminalWizard(input_stream=key_input, output_stream=io.StringIO(), color=False)

    assert (
        choose_many_checkbox(term, "Skills", [("ls-context", "ls-context")], default=["ls-context"])
        == wizard.CANCEL
    )


def test_wizard_full_flow_renders_guided_context_for_current_repo(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    source = Path(__file__).resolve().parents[2]
    shutil.copytree(source / "_localsetup" / "docs", root / "_localsetup" / "docs", dirs_exist_ok=True)
    home = tmp_path / "home"
    caller = tmp_path / "caller"
    caller.mkdir()
    output = io.StringIO()
    term = TerminalWizard(
        input_stream=io.StringIO("\n\n2\n\n1,3\nyes\n"),
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
    assert "Skill Groups" not in rendered
    assert "Individual Skills" not in rendered
    assert "\nApplying\n" in rendered
    assert "\nResult\n" in rendered
    assert "Source and Release" in rendered
    assert "Global Package Library" in rendered
    assert "Repo Setup" in rendered
    assert "Repo Adapters" in rendered
    assert "Review" in rendered
    assert "Result" in rendered
    rendered_words = " ".join(rendered.split())
    assert "Decides: Confirms the installer source and release channel before package choices." in rendered_words
    assert "Suggested: No repo setup" in rendered
    assert "Writes adapter path .codex/skills." in rendered
    assert "Code, docs, git, testing, markdown validation, and repo repair workflows." in rendered
    assert "Global packs" in rendered
    assert "Repo-visible packages" in rendered
    assert (
        "Does: Shows source, target, packs, adapter mode, dependency mode, and concrete filesystem actions before changes."
        in rendered_words
    )
    assert "Does: Verification checked the managed library and selected adapter paths after applying the plan." in rendered_words
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
        input_stream=io.StringIO("\n\n\nyes\n"),
        output_stream=output,
        color=False,
    )

    def interrupt_apply(term: TerminalWizard, state: wizard.WizardState) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr(wizard, "_apply_and_show_result", interrupt_apply)

    code = run_wizard(repo_root=root, home=home, caller_directory=root, terminal=term, register_shell=False)

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
        input_stream=io.StringIO("\n\n\nyes\n"),
        output_stream=io.StringIO(),
        color=False,
    )

    code = run_wizard(repo_root=root, home=home, caller_directory=root, terminal=term, register_shell=False)

    assert code == 0
    assert (home / ".local/share/localsetup/packages/ls-context").is_dir()
    assert not (root / ".codex").exists()


def test_wizard_no_repo_rerun_detaches_managed_adapters_and_preserves_global_packages(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    source = Path(__file__).resolve().parents[2]
    shutil.copytree(source / "_localsetup" / "docs", root / "_localsetup" / "docs", dirs_exist_ok=True)
    home = tmp_path / "home"
    apply_plan(
        root,
        build_install_plan(root, home=home, global_packs=["dev"], repo_packs=["core"], platform_ids=["codex"]),
        home=home,
    )
    assert (root / ".codex" / "skills").is_dir()
    assert (home / ".local/share/localsetup/packages/ls-nodejs-nextjs").is_dir()

    output = io.StringIO()
    term = TerminalWizard(
        input_stream=io.StringIO("\n\n1\nyes\n"),
        output_stream=output,
        color=False,
    )

    code = run_wizard(repo_root=root, home=home, caller_directory=root, terminal=term, register_shell=False)

    rendered = output.getvalue()
    lock = load_json(root / ".localsetup/lock.json")
    assert code == 0
    assert "Repo Adapters" not in rendered
    assert "Detached adapters" in rendered
    assert not (root / ".codex" / "skills").exists()
    assert (home / ".local/share/localsetup/packages/ls-nodejs-nextjs").is_dir()
    assert lock["global_only"] is True
    assert lock["adapter_targets"] == []
    assert lock["platforms"] == []


def test_wizard_no_repo_detach_ignores_absolute_adapter_outside_target(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    source = Path(__file__).resolve().parents[2]
    shutil.copytree(source / "_localsetup" / "docs", root / "_localsetup" / "docs", dirs_exist_ok=True)
    home = tmp_path / "home"
    target = tmp_path / "target"
    target.mkdir()
    global_root = home / ".local/share/localsetup/packages"
    global_root.mkdir(parents=True)
    inside = target / ".codex" / "skills"
    inside.parent.mkdir(parents=True)
    inside.symlink_to(global_root, target_is_directory=True)
    outside = tmp_path / "outside-skills"
    outside.symlink_to(global_root, target_is_directory=True)
    lock_path = target / ".localsetup" / "lock.json"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text(
        json.dumps(
            {
                "target_root": str(target),
                "platforms": ["codex"],
                "adapter_targets": [
                    {"path": str(inside), "packages": ["ls-context"]},
                    {"path": str(outside), "packages": ["ls-context"]},
                ],
                "global_baseline_selectors": {"packs": ["core"]},
                "repo_selectors": {"packs": ["core"]},
            }
        ),
        encoding="utf-8",
    )
    term = TerminalWizard(
        input_stream=io.StringIO("\n\n1\nyes\n"),
        output_stream=io.StringIO(),
        color=False,
    )

    code = run_wizard(repo_root=root, home=home, caller_directory=target, terminal=term, register_shell=False)

    assert code == 0
    assert not inside.exists()
    assert outside.is_symlink()


def test_wizard_legacy_lock_selectors_seed_global_and_repo_defaults(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    adapter = root / ".codex" / "skills"
    lock_path = root / ".localsetup" / "lock.json"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text(
        json.dumps(
            {
                "version": 2,
                "target_root": str(root),
                "platforms": ["codex"],
                "attach_mode": "symlink",
                "dependency_mode": "prompt-only",
                "selectors": {
                    "preset": "custom",
                    "packs": ["dev"],
                    "skills": ["ls-context"],
                    "skill_classes": ["development"],
                    "skill_tags": ["git"],
                    "exclude_skills": ["ls-linux-patcher"],
                },
                "adapter_targets": [{"platform": "codex", "path": str(adapter), "mode": "symlink"}],
            }
        ),
        encoding="utf-8",
    )
    state = wizard.WizardState(repo_root=root.resolve(), home=home.resolve(), caller_directory=root.resolve())

    wizard._load_prior_defaults(state)

    assert state.global_packs == ["dev"]
    assert state.global_preset == "custom"
    assert state.global_skills == ["ls-context"]
    assert state.global_skill_classes == ["development"]
    assert state.global_skill_tags == ["git"]
    assert state.global_exclude_skills == ["ls-linux-patcher"]
    assert state.repo_packs == ["dev"]
    assert state.repo_preset == "custom"
    assert state.repo_skills == ["ls-context"]
    assert state.repo_skill_classes == ["development"]
    assert state.repo_skill_tags == ["git"]
    assert state.repo_exclude_skills == ["ls-linux-patcher"]


def test_wizard_root_legacy_lock_selectors_seed_global_and_repo_defaults(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    adapter = root / ".codex" / "skills"
    (root / "localsetup.lock.json").write_text(
        json.dumps(
            {
                "version": 1,
                "target_root": str(root),
                "platforms": ["codex"],
                "selectors": {
                    "preset": "custom",
                    "packs": ["dev"],
                    "skills": ["ls-context"],
                    "skill_classes": ["development"],
                    "skill_tags": ["git"],
                    "exclude_skills": ["ls-linux-patcher"],
                },
                "adapter_targets": [{"platform": "codex", "path": str(adapter), "mode": "symlink"}],
            }
        ),
        encoding="utf-8",
    )
    state = wizard.WizardState(repo_root=root.resolve(), home=home.resolve(), caller_directory=root.resolve())

    wizard._load_prior_defaults(state)

    assert state.global_packs == ["dev"]
    assert state.global_preset == "custom"
    assert state.global_skills == ["ls-context"]
    assert state.global_skill_classes == ["development"]
    assert state.global_skill_tags == ["git"]
    assert state.global_exclude_skills == ["ls-linux-patcher"]
    assert state.repo_packs == ["dev"]
    assert state.repo_preset == "custom"
    assert state.repo_skills == ["ls-context"]
    assert state.repo_skill_classes == ["development"]
    assert state.repo_skill_tags == ["git"]
    assert state.repo_exclude_skills == ["ls-linux-patcher"]


def test_wizard_custom_preset_can_install_individual_skill_without_pack(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    source = Path(__file__).resolve().parents[2]
    shutil.copytree(source / "_localsetup" / "docs", root / "_localsetup" / "docs", dirs_exist_ok=True)
    home = tmp_path / "home"
    term = TerminalWizard(
        input_stream=io.StringIO("\n\n\nyes\n"),
        output_stream=io.StringIO(),
        color=False,
    )

    code = run_wizard(
        repo_root=root,
        home=home,
        caller_directory=root,
        terminal=term,
        preset="custom",
        skills=["ls-context"],
        register_shell=False,
    )

    lock = load_json(root / ".localsetup/lock.json")
    assert code == 0
    assert (home / ".local/share/localsetup/packages/ls-context").is_dir()
    assert not (home / ".local/share/localsetup/packages/ls-test-runner").exists()
    assert lock["skills"] == ["ls-context"]


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
        input_stream=io.StringIO("\n\n\n\n\nyes\n"),
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
    assert_scoped_adapter(target / ".cursor" / "skills", "ls-context")
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
        input_stream=io.StringIO("\n\n\n\nyes\n"),
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


def test_migration_scanner_and_hook_gate(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    (root / "README.md").write_text("Use localsetup-context during migration.\n", encoding="utf-8")
    alias_doc = root / "_localsetup" / "docs" / "_generated" / "skill_aliases.json"
    alias_doc.write_text('{"localsetup-context": "ls-context"}\n', encoding="utf-8")
    pack_doc = root / "_localsetup" / "docs" / "_generated" / "skill-packs.md"
    pack_doc.write_text("| `core` | `skill` | `ls-context` | `localsetup-context` |\n", encoding="utf-8")
    migration_doc = root / "_localsetup" / "docs" / "migration" / "skill-alias-map.md"
    migration_doc.write_text("| `localsetup-context` | `ls-context` |\n", encoding="utf-8")
    private_backup = root / ".localsetup" / "backups" / "audit" / "localsetup.lock.json"
    private_backup.parent.mkdir(parents=True)
    private_backup.write_text('{"aliases": {"localsetup-context": "ls-context"}}\n', encoding="utf-8")
    runtime_note = root / ".codex" / "runs" / "20260512-note.md"
    runtime_note.parent.mkdir(parents=True)
    runtime_note.write_text("Use localsetup-context in runtime notes only.\n", encoding="utf-8")
    heartbeat_note = root / ".localsetup" / "state" / "codex-heartbeat" / "latest.json"
    heartbeat_note.parent.mkdir(parents=True)
    heartbeat_note.write_text('{"note": "Use localsetup-context in runtime state only."}\n', encoding="utf-8")
    runtime_lock = root / ".localsetup" / "lock.json"
    runtime_lock.write_text('{"note": "Use localsetup-context in runtime lock only."}\n', encoding="utf-8")

    findings = scan_legacy_references(root)
    paths = {finding["path"] for finding in findings}
    by_path = {finding["path"]: finding for finding in findings}
    assert "README.md" in paths
    assert by_path["README.md"]["category"] == "actionable"
    assert by_path["README.md"]["actionable"] is True
    assert by_path["_localsetup/docs/_generated/skill_aliases.json"]["category"] == "expected_alias_surface"
    assert by_path["_localsetup/docs/_generated/skill_aliases.json"]["actionable"] is False
    assert by_path["_localsetup/docs/_generated/skill-packs.md"]["category"] == "expected_alias_surface"
    assert by_path["_localsetup/docs/migration/skill-alias-map.md"]["category"] == "expected_migration_map"
    assert by_path[".localsetup/backups/audit/localsetup.lock.json"]["category"] == "ignored_private_backup"
    assert all({"path", "line", "text"} <= set(finding) for finding in findings)
    assert {finding["path"] for finding in scan_legacy_references(root, include_expected=False)} == {"README.md"}
    assert ".codex/runs/20260512-note.md" not in paths
    assert ".localsetup/state/codex-heartbeat/latest.json" not in paths
    assert ".localsetup/lock.json" not in paths

    tool = root / "_localsetup" / "tools" / "localsetup.py"
    plain = subprocess.run(
        [sys.executable, str(tool), "--source-root", str(root), "scan-migration"],
        text=True,
        capture_output=True,
        check=True,
    )
    with_expected = subprocess.run(
        [sys.executable, str(tool), "--source-root", str(root), "scan-migration", "--include-expected"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert {finding["path"] for finding in json.loads(plain.stdout)["findings"]} == {"README.md"}
    assert ".localsetup/backups/audit/localsetup.lock.json" in {
        finding["path"] for finding in json.loads(with_expected.stdout)["findings"]
    }

    gate = run_maintainer_gate(root, tmp_path / "artifact.tar.gz")
    assert gate["ok"] is True
    assert gate["package"]["leaks"] == []


def test_conservative_migration_renames_managed_legacy_global_skill(tmp_path: Path) -> None:
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


def test_conservative_migration_refuses_unmanaged_adapter(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    collision = root / ".codex" / "skills"
    collision.mkdir(parents=True)
    (collision / "custom.txt").write_text("user content\n", encoding="utf-8")

    report = conservative_migrate(root, home=home, platform_ids=["codex"], backup_dir=tmp_path / "backup")

    assert report["ok"] is False
    assert report["blockers"]
    assert "mv " in report["blockers"][0]["remediation"]


def test_convert_blocks_unmanaged_adapter_content(tmp_path: Path) -> None:
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


def test_convert_archives_old_framework_and_installs_at_target(tmp_path: Path) -> None:
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
    assert_scoped_adapter(target / ".codex" / "skills", "ls-context")
    assert (target / ".localsetup/lock.json").is_file()
    assert report["verify"]["ok"] is True


def test_convert_cli_accepts_split_selector_flags(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target"
    target.mkdir()
    tool = root / "_localsetup" / "tools" / "localsetup.py"

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
            "convert",
            "--platforms",
            "codex",
            "--global-packs",
            "dev",
            "--repo-packs",
            "core",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert payload["applied"] is False


def test_convert_does_not_copy_framework_source(tmp_path: Path) -> None:
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


def test_convert_uv_sync_uses_source_checkout_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "custom-home"
    target = tmp_path / "target"
    monkeypatch.setenv("LOCALSETUP_UV_BIN", "uv")
    commands: list[list[str]] = []

    def fake_runner(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        commands.append(cmd)
        if cmd[-1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="uv 0.11.5\n", stderr="")
        if "sync" in cmd:
            python_path = root / ".venv" / "bin" / "python"
            python_path.parent.mkdir(parents=True, exist_ok=True)
            python_path.write_text("# fake python\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    def fake_ensure_dependencies(
        repo_root: Path,
        *,
        mode: str,
        data_root: Path | None = None,
        target_root: Path | None = None,
        runner: object | None = None,
    ) -> dict:
        return ensure_dependencies(repo_root, mode=mode, data_root=data_root, target_root=target_root, runner=fake_runner)

    monkeypatch.setattr(conversion_mod, "ensure_dependencies", fake_ensure_dependencies)

    report = convert_repo(
        root,
        home=home,
        packs=["core"],
        platform_ids=["codex"],
        target_root=target,
        dependency_mode="uv-sync",
        apply=True,
    )

    interpreter = report["install"]["dependencies"]["interpreter"]
    assert report["ok"] is True
    assert any("sync" in cmd and "--locked" in cmd for cmd in commands)
    assert interpreter.endswith(".venv/bin/python")
    assert str(root) in interpreter


def test_convert_late_migration_blocker_does_not_remove_target_framework(tmp_path: Path) -> None:
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


def test_hook_gate_accepts_mock_runner(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    runner = tmp_path / "mock_runner.sh"
    runner.write_text("#!/usr/bin/env bash\nprintf '{\"ok\": true}\\n'\n", encoding="utf-8")
    runner.chmod(0o755)

    gate = run_maintainer_gate(root, tmp_path / "artifact.tar.gz", runner=str(runner))

    assert gate["ok"] is True
    assert gate["agent_runner"]["returncode"] == 0
    assert gate["agent_runner"]["json"] == {"ok": True}


def test_refuses_unmanaged_skill_collision(tmp_path: Path) -> None:
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


def test_failed_apply_marks_journal_and_cleans_staging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_failed_package_promotion_restores_existing_managed_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_failed_late_commit_restores_packages_and_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_failed_adapter_replace_restores_existing_adapter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    plan = build_install_plan(root, home=home, packs=["core"], attach_mode="portable", platform_ids=["codex"])
    apply_plan(root, plan, home=home, dry_run=False)
    adapter = root / ".codex" / "skills"
    existing_note = adapter / "existing.txt"
    existing_note.write_text("keep me\n", encoding="utf-8")
    original_copytree = apply_mod.shutil.copytree

    def fail_adapter_copy(src: Path, dst: Path, *args: object, **kwargs: object):
        if Path(dst).parent == adapter:
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


def test_rollback_reads_legacy_lock_and_removes_relative_managed_adapter(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    pack_path = root / "_localsetup" / "config" / "pack.yaml"
    pack_path.write_text(
        pack_path.read_text(encoding="utf-8").replace("  lockfile: .localsetup/lock.json", "  lockfile: custom-lock.json"),
        encoding="utf-8",
    )
    global_root = home / ".local" / "share" / "localsetup" / "packages"
    package = global_root / "ls-context"
    package.mkdir(parents=True)
    (package / MARKER_JSON).write_text("{}\n", encoding="utf-8")
    adapter = root / "relative-adapter"
    adapter.symlink_to(global_root, target_is_directory=True)
    legacy_lock = root / "localsetup.lock.json"
    legacy_lock.write_text(
        json.dumps(
            {
                "installed_skills": [str(package)],
                "installed_workflows": [],
                "adapter_state": ["relative-adapter"],
            }
        ),
        encoding="utf-8",
    )

    result = rollback(root, home=home)

    assert str(package) in result["removed"]
    assert str(adapter) in result["removed"]
    assert str(global_root) in result["removed"]
    assert str(legacy_lock) in result["removed"]
    assert not adapter.exists()
    assert not global_root.exists()


def test_repo_path_rejects_symlink_parent_escape(tmp_path: Path) -> None:
    from _localsetup.core.paths import PathValidationError, repo_path

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
    artifact = tmp_path / "localsetup-public.tar.gz"

    package = build_public_artifact(root, artifact)

    assert "_localsetup/token.secret" in package["leaks"]
    assert scan_tar_for_leaks(artifact, [".localsetup-maint"]) == package["leaks"]


def test_query_payloads_cover_catalog_reasoning_graph_and_adoption(tmp_path: Path) -> None:
    from _localsetup.core.query import adopt_recommendations, graph_payload, pack_reasoning, skill_payload, workflow_payload

    root = make_temp_repo(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    (target / "package.json").write_text("{}", encoding="utf-8")
    (target / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (target / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    (target / "main.tf").write_text("terraform {}\n", encoding="utf-8")
    (target / "nginx.conf").write_text("events {}\n", encoding="utf-8")
    (target / "demo.service").write_text("[Service]\n", encoding="utf-8")
    (target / ".github" / "workflows").mkdir(parents=True)

    skills = skill_payload(root, "context")
    workflows = workflow_payload(root, "heartbeat")
    reasoning = pack_reasoning(root, ["core"])
    graph = graph_payload(root)
    adoption = adopt_recommendations(target)

    assert skills["count"] >= 1
    assert all("risk" in item and "permissions" in item for item in skills["skills"])
    assert workflows["count"] >= 1
    assert reasoning["packs"][0]["reason"] == "selected explicitly"
    assert any(edge["type"] == "pack_skill" for edge in graph["edges"])
    assert adoption["signals"]["node"] is True
    assert adoption["signals"]["python"] is True
    assert adoption["signals"]["docker"] is True
    assert adoption["signals"]["github_actions"] is True
    assert adoption["signals"]["terraform"] is True
    assert adoption["signals"]["nginx"] is True
    assert adoption["signals"]["systemd"] is True


def test_global_first_audit_reports_legacy_and_doc_claims(tmp_path: Path) -> None:
    from _localsetup.core.global_first_audit import _relative, audit_global_first

    source = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target"
    target.mkdir()
    (target / "_localsetup").mkdir()
    (target / "localsetup.lock.json").write_text("{}", encoding="utf-8")
    (source / "install.ps1").write_text("retired\n", encoding="utf-8")
    (source / "_localsetup" / "tools" / "deploy").write_text("legacy\n", encoding="utf-8")
    (source / "README.md").write_text(
        "Run python3 _localsetup/tools/localsetup.py verify here.\n"
        "Allowed source-checkout command: python3 _localsetup/tools/localsetup.py verify --source-root . --target-directory .\n",
        encoding="utf-8",
    )
    old_root = home / ".local" / "share" / "agents" / "skills" / "localsetup"
    old_root.mkdir(parents=True)
    package_root = home / ".local" / "share" / "localsetup" / "packages"
    (package_root / "localsetup-old").mkdir(parents=True)

    payload = audit_global_first(source, home=home, target_root=target)

    blocker_kinds = {item["kind"] for item in payload["blockers"]}
    warning_kinds = {item["kind"] for item in payload["warnings"]}
    assert payload["ok"] is False
    assert "stale_framework_source" in blocker_kinds
    assert "legacy_root_lockfile" in blocker_kinds
    assert "retired_powershell_surface" in blocker_kinds
    assert "legacy_deploy_surface" in blocker_kinds
    assert "docs_claim" in blocker_kinds
    assert "legacy_package_root" in warning_kinds
    assert any(
        observation["kind"] == "legacy_package_dirs" and observation["present"] == ["localsetup-old"]
        for observation in payload["observations"]
    )
    assert _relative(tmp_path / "outside.md", source).endswith("outside.md")


def test_diff_plan_current_compares_lockfile_to_planned_selection(tmp_path: Path) -> None:
    from _localsetup.core.diffing import diff_plan_current

    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    apply_plan(root, build_install_plan(root, home=home, packs=["core"], platform_ids=["codex"]), home=home)

    diff = diff_plan_current(
        root,
        home=home,
        packs=None,
        global_packs=["dev"],
        repo_packs=["dev"],
        platform_ids=["codex", "kilo"],
        target_root=None,
        attach_mode="symlink",
    )

    assert "ls-nodejs-nextjs" in diff["skills"]["added"]
    assert any(path.endswith(".kilo/skills") for path in diff["adapters"]["added"])
    assert diff["has_lockfile"] is True


def test_legacy_wizard_advanced_selector_steps_remain_callable(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    state = wizard.WizardState(
        repo_root=root,
        home=tmp_path / "home",
        caller_directory=root,
        target_directory=root,
        packs=["core"],
        platforms=["codex"],
    )
    term = TerminalWizard(
        input_stream=io.StringIO("\n\n\n\n\n"),
        output_stream=io.StringIO(),
        color=False,
    )

    assert wizard._skill_group_step(term, state) == "continue"
    assert wizard._skill_individual_step(term, state) == "continue"
    assert wizard._options_step(term, state) == "continue"
    assert state.skills
    assert state.attach_mode == "symlink"
    assert state.dependency_mode == "prompt-only"


def test_cli_dispatches_stubbed_branches_without_heavy_side_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    report = tmp_path / "report.json"
    out = tmp_path / "out.json"
    artifact = tmp_path / "artifact.tar.gz"

    fake_plan = SimpleNamespace(actions=[], rollback_metadata={"skills": [], "workflows": [], "platforms": [], "global_only": True})
    monkeypatch.setattr(cli_mod, "build_install_plan", lambda *args, **kwargs: fake_plan)
    monkeypatch.setattr(cli_mod, "_policy_findings", lambda *args, **kwargs: {"mode": "standard", "warnings": [], "blockers": []})
    monkeypatch.setattr(cli_mod, "install_inventory", lambda *args, **kwargs: {"items": []})
    monkeypatch.setattr(cli_mod, "apply_plan", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(cli_mod, "ensure_dependencies", lambda *args, **kwargs: {"ok": True, "changed": False})
    monkeypatch.setattr(cli_mod, "verify_install", lambda *args, **kwargs: {"ok": True, "issues": []})
    monkeypatch.setattr(cli_mod, "rollback", lambda *args, **kwargs: {"removed": []})
    monkeypatch.setattr(cli_mod, "run_wizard", lambda **kwargs: 0)
    monkeypatch.setattr(cli_mod, "adapter_status", lambda *args, **kwargs: [])
    monkeypatch.setattr(cli_mod, "recorded_adapter_status", lambda *args, **kwargs: [])
    monkeypatch.setattr(cli_mod, "provenance_report", lambda *args, **kwargs: {"warnings": [], "repair_hints": []})
    monkeypatch.setattr(cli_mod, "run_doctor", lambda *args, **kwargs: {"ok": True, "warnings": [], "blockers": []})
    monkeypatch.setattr(cli_mod, "shell_registration_status", lambda *args, **kwargs: {"warnings": []})
    monkeypatch.setattr(cli_mod, "conservative_migrate", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(cli_mod, "convert_repo", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(cli_mod, "build_agent_context", lambda *args, **kwargs: {"blockers": []})
    monkeypatch.setattr(cli_mod, "render_markdown_report", lambda payload: "# stub\n")
    monkeypatch.setattr(cli_mod, "generate_alias_outputs", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(cli_mod, "repo_finalizer_plan", lambda *args, **kwargs: {"ok": True, "action": "plan"})
    monkeypatch.setattr(cli_mod, "repo_finalizer_status", lambda *args, **kwargs: {"ok": True, "action": "status"})
    monkeypatch.setattr(cli_mod, "repo_finalizer_run", lambda *args, **kwargs: {"ok": True, "action": "run"})
    monkeypatch.setattr(cli_mod, "repo_finalizer_payload_to_text", lambda payload: f"{payload['action']}\n")
    monkeypatch.setattr(cli_mod, "harness_plan", lambda *args, **kwargs: {"ok": True, "action": "plan"})
    monkeypatch.setattr(cli_mod, "harness_init", lambda *args, **kwargs: {"ok": True, "action": "init"})
    monkeypatch.setattr(cli_mod, "harness_enable", lambda *args, **kwargs: {"ok": True, "action": "enable"})
    monkeypatch.setattr(cli_mod, "harness_disable", lambda *args, **kwargs: {"ok": True, "action": "disable"})
    monkeypatch.setattr(cli_mod, "harness_status", lambda *args, **kwargs: {"ok": True, "action": "status"})
    monkeypatch.setattr(cli_mod, "harness_run", lambda *args, **kwargs: {"ok": True, "action": "run"})
    monkeypatch.setattr(cli_mod, "harness_payload_to_text", lambda payload: f"{payload['action']}\n")
    monkeypatch.setattr(cli_mod, "load_skill_catalog", lambda *args, **kwargs: [])
    monkeypatch.setattr(cli_mod, "load_workflow_catalog", lambda *args, **kwargs: [])
    monkeypatch.setattr(cli_mod, "diff_plan_current", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(cli_mod, "skill_payload", lambda *args, **kwargs: {"count": 1, "skills": []})
    monkeypatch.setattr(cli_mod, "workflow_payload", lambda *args, **kwargs: {"count": 1, "workflows": []})
    monkeypatch.setattr(cli_mod, "pack_reasoning", lambda *args, **kwargs: {"packs": []})
    monkeypatch.setattr(cli_mod, "graph_payload", lambda *args, **kwargs: {"edges": []})
    monkeypatch.setattr(cli_mod, "adopt_recommendations", lambda *args, **kwargs: {"recommended_packs": []})
    monkeypatch.setattr(cli_mod, "write_source_sbom", lambda *args, **kwargs: {"ok": True, "kind": "source"})
    monkeypatch.setattr(cli_mod, "write_installed_sbom", lambda *args, **kwargs: {"ok": True, "kind": "installed"})
    monkeypatch.setattr(cli_mod, "validate_manifest_schemas", lambda *args, **kwargs: [])
    monkeypatch.setattr(cli_mod, "validate_skill_catalog", lambda *args, **kwargs: [])
    monkeypatch.setattr(cli_mod, "validate_workflow_catalog", lambda *args, **kwargs: [])
    monkeypatch.setattr(cli_mod, "scan_legacy_references", lambda *args, **kwargs: [])
    monkeypatch.setattr(cli_mod, "audit_global_first", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(cli_mod, "run_maintainer_gate", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(cli_mod, "plan_version", lambda *args, **kwargs: {"ok": True, "bump": "none", "target_version": "9.9.9"})
    monkeypatch.setattr(cli_mod, "push_lines_to_plans", lambda *args, **kwargs: [{"ok": True}])
    monkeypatch.setattr(cli_mod, "check_version_files", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(cli_mod, "sync_version_files", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(cli_mod, "stage_version_files", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli_mod, "commit_version_sync", lambda *args, **kwargs: "abc123")
    monkeypatch.setattr(cli_mod, "_run_self_refresh", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(cli_mod, "register_shell_command", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(cli_mod, "build_public_artifact", lambda *args, **kwargs: {"ok": True, "leaks": []})
    monkeypatch.setattr(cli_mod, "verify_release_artifact", lambda *args, **kwargs: {"ok": True})

    def fake_subprocess_run(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli_mod.subprocess, "run", fake_subprocess_run)

    def run_cli(*args: str) -> str:
        code = cli_mod._main(["--source-root", str(root), "--home", str(home), *args])
        output = capsys.readouterr().out
        assert code == 0
        return output

    run_cli("plan", "--report", str(report), "--global-packs", "core", "--repo-packs", "dev")
    assert report.is_file()
    run_cli("install", "--apply", "--target-directory", str(root), "--platforms", "codex")
    run_cli("wizard", "--caller-directory", str(root), "--target-directory-origin", "inferred", "--no-register-shell")
    run_cli("verify", "--platforms", "codex")
    run_cli("rollback", "--platforms", "codex")
    run_cli("adapters", "--platforms", "codex")
    run_cli("adapters", "--provenance")
    run_cli("configure", "--home-override", str(home), "--global-preset", "core")
    run_cli("doctor", "--platforms", "codex")
    run_cli("provenance", "repair", "--plan")
    run_cli("provenance", "report", "--platforms", "codex")
    run_cli("migrate", "--dry-run", "--platforms", "codex")
    run_cli("convert", "--apply", "--global-packs", "core", "--repo-packs", "dev", "--platforms", "codex")
    run_cli("context", "--markdown", "--report", str(tmp_path / "context.md"))
    run_cli("generate-docs")
    run_cli("harness", "repo-finalizer", "plan", "--json")
    run_cli("harness", "repo-finalizer", "status")
    run_cli("harness", "repo-finalizer", "run", "--json", "--no-commit", "--checkpoint", "--message", "checkpoint")
    run_cli("harness", "codex-heartbeat", "plan")
    run_cli("harness", "codex-heartbeat", "init")
    run_cli("harness", "codex-heartbeat", "enable", "--install-crontab", "--yes")
    run_cli("harness", "codex-heartbeat", "disable", "--install-crontab", "--yes")
    run_cli("harness", "codex-heartbeat", "status")
    run_cli("harness", "codex-heartbeat", "run", "--no-agent", "--force")
    run_cli("docs-align", "inventory")
    run_cli("context-index", "refresh")
    run_cli("catalog")
    run_cli("diff", "--packs", "core")
    run_cli("skill", "search", "context")
    run_cli("workflow", "search", "heartbeat")
    run_cli("why", "--packs", "core")
    run_cli("graph")
    run_cli("adopt", "--target-directory", str(root))
    run_cli("detach", "--platforms", "codex")
    run_cli("sbom", "--out", str(out))
    run_cli("sbom", "--installed", "--out", str(tmp_path / "installed.json"), "--target-directory", str(root))
    run_cli("validate-catalog")
    run_cli("scan-migration", "--include-expected")
    run_cli("audit-global-first", "--target-directory", str(root))
    run_cli("hook-gate", "--out", str(artifact), "--runner", "pytest")
    run_cli("version-plan")
    monkeypatch.setattr(cli_mod.sys, "stdin", io.StringIO("refs/heads/main abc refs/heads/main def\n"))
    run_cli("version-plan", "--push-stdin")
    run_cli("version-sync", "--check")
    run_cli("version-sync", "--target", "9.9.9", "--stage", "--commit")
    run_cli("release-push", "--", "origin", "main")
    run_cli("self-refresh", "--packs", "core", "--platforms", "codex")
    run_cli("install-hooks")
    run_cli("register-shell")
    run_cli("package", "--out", str(tmp_path / "pkg.tar.gz"))
    run_cli("verify-release", str(tmp_path / "pkg.tar.gz"), "--expected-tag", "v9.9.9")

    assert cli_mod.main(["configure", "--packs", "core,,dev"]) == 2
    assert "empty value in comma-separated list" in capsys.readouterr().err


def test_cli_self_refresh_mixed_modes_and_success_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    config = InstallConfig(target_directory=str(root), dependency_mode="prompt-only")

    monkeypatch.setattr(
        cli_mod,
        "_existing_target_platforms",
        lambda *args, **kwargs: [
            {"platform": "codex", "mode": "symlink"},
            {"platform": "cursor", "mode": "portable"},
        ],
    )
    mixed = cli_mod._run_self_refresh(root, config, home)
    assert mixed["ok"] is False
    assert "mixed existing adapter modes" in mixed["issues"][0]

    fake_plan = SimpleNamespace(rollback_metadata={})
    monkeypatch.setattr(cli_mod, "_existing_target_platforms", lambda *args, **kwargs: [{"platform": "codex", "mode": "symlink"}])
    monkeypatch.setattr(cli_mod, "build_install_plan", lambda *args, **kwargs: fake_plan)
    monkeypatch.setattr(cli_mod, "apply_plan", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(cli_mod, "verify_install", lambda *args, **kwargs: {"ok": True})

    refreshed = cli_mod._run_self_refresh(root, config, home)
    assert refreshed["ok"] is True
    assert refreshed["selected"]["platforms"] == ["codex"]
    assert refreshed["selected"]["attach_mode"] == "symlink"


def test_wizard_control_helpers_cover_help_detail_and_error_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = io.StringIO()
    term = TerminalWizard(input_stream=io.StringIO(), output_stream=output, color=False)

    monkeypatch.setattr(wizard.shutil, "get_terminal_size", lambda fallback: (_ for _ in ()).throw(OSError("no tty")))
    assert term.width() == 88
    term.key_value_block([("Empty", "")])
    term.choice_row(1, Choice("risky", "Risky", "summary", "effect", "best", "tradeoff", caution="careful"))
    monkeypatch.setenv("TERM", "dumb")
    term.clear_screen()
    assert "\033[2J" not in output.getvalue()

    with pytest.raises(ValueError, match="invalid color mode"):
        TerminalWizard(io.StringIO(), io.StringIO(), color_mode="loud")
    with pytest.raises(ValueError, match="invalid glyphs mode"):
        TerminalWizard(io.StringIO(), io.StringIO(), glyph_mode="emoji")
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("no tty")))
    with pytest.raises(RuntimeError, match="interactive installer requires a terminal"):
        wizard.open_tty()

    continue_term = TerminalWizard(io.StringIO("?\nd\nd\n\n"), io.StringIO(), color=False)
    assert wizard._continue_prompt(
        continue_term,
        "Continue",
        help_text="Helpful text.",
        detail_text="Detailed text.",
    ) == "continue"
    assert "Helpful text." in continue_term.output.getvalue()
    assert "Detailed text." in continue_term.output.getvalue()

    confirm_term = TerminalWizard(io.StringIO("?\nd\nyes\n"), io.StringIO(), color=False)
    assert wizard._confirm_apply(confirm_term) == "apply"
    assert "Type yes only after" in confirm_term.output.getvalue()
    assert "writes the managed library" in confirm_term.output.getvalue()
    assert wizard._confirm_apply(TerminalWizard(io.StringIO("no\n"), io.StringIO(), color=False)) == wizard.BACK
    assert wizard._blocker_prompt(TerminalWizard(io.StringIO("?\nd\nx\n"), io.StringIO(), color=False)) == wizard.BACK
    assert wizard._target_directory_prompt(TerminalWizard(io.StringIO("?\nd\n/tmp/repo\n"), io.StringIO(), color=False)) == "/tmp/repo"

    invalid_choice = TerminalWizard(io.StringIO("bad\nGlobal\n"), io.StringIO(), color=False)
    assert choose_one(invalid_choice, "Mode", [("global", "Global")], default="global") == "global"
    invalid_many = TerminalWizard(io.StringIO("bad\n0\n"), io.StringIO(), color=False)
    assert choose_many(invalid_many, "Packs", [("core", "Core")], default=[], allow_none=True) == []


def test_wizard_checkbox_key_mode_covers_bulk_help_back_and_empty_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    choices = [("core", "Core"), ("dev", "Dev")]

    stream = FakeKeyInput("?djank\n")
    enable_checkbox_key_mode(monkeypatch, stream)
    term = TerminalWizard(input_stream=stream, output_stream=io.StringIO(), color=False)
    assert choose_many_checkbox(term, "Packs", choices, default=["core"], allow_none=True, help_text="Toggle packs.") == []
    rendered = term.output.getvalue()
    assert "Toggle packs." in rendered
    assert "Detail mode: compact." in rendered

    back_stream = FakeKeyInput("b")
    enable_checkbox_key_mode(monkeypatch, back_stream)
    assert (
        choose_many_checkbox(
            TerminalWizard(input_stream=back_stream, output_stream=io.StringIO(), color=False),
            "Packs",
            choices,
            default=[],
        )
        == wizard.BACK
    )

    empty_stream = FakeKeyInput("")
    patch_fake_key_input(monkeypatch, empty_stream)
    term = TerminalWizard(input_stream=empty_stream, output_stream=io.StringIO(), color=False)
    assert wizard._read_escape_sequence(term) == ""


def test_wizard_review_blockers_apply_failure_and_warning_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = make_temp_repo(tmp_path)
    state = wizard.WizardState(
        repo_root=root,
        home=tmp_path / "home",
        caller_directory=root,
        target_directory=root,
        platforms=["codex"],
        global_packs=["core"],
        repo_packs=["core"],
    )
    fake_action = SimpleNamespace(kind="attach_repo_path", path=root / ".codex" / "skills", details={"platform": "codex"})
    fake_plan = SimpleNamespace(
        actions=[fake_action],
        rollback_metadata={
            "global_baseline_packs": ["core"],
            "repo_packs": ["core"],
            "global_baseline_packages": ["ls-context"],
            "repo_packages": ["ls-context"],
            "skills": ["ls-context"],
            "workflows": [],
        },
    )
    monkeypatch.setattr(wizard, "build_install_plan", lambda *args, **kwargs: fake_plan)
    monkeypatch.setattr(wizard, "run_doctor", lambda *args, **kwargs: {"warnings": ["warn"], "blockers": ["block"]})

    blocker_term = TerminalWizard(io.StringIO("?\nd\nb\n"), io.StringIO(), color=False)
    assert wizard._review_step(blocker_term, state) == wizard.BACK
    assert "Diagnostic command:" in blocker_term.output.getvalue()

    monkeypatch.setattr(wizard, "build_install_plan", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    failed_term = TerminalWizard(io.StringIO(), io.StringIO(), color=False)
    assert wizard._apply_and_show_result(failed_term, state) == 2
    assert "Install failed." in failed_term.output.getvalue()

    monkeypatch.setattr(wizard, "build_install_plan", lambda *args, **kwargs: fake_plan)
    monkeypatch.setattr(wizard, "ensure_dependencies", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(wizard, "apply_plan", lambda *args, **kwargs: {"ok": True, "lockfile": str(root / ".localsetup" / "lock.json")})
    monkeypatch.setattr(wizard, "register_shell_command", lambda *args, **kwargs: {"warnings": ["path warning"]})
    monkeypatch.setattr(wizard, "verify_install", lambda *args, **kwargs: {"ok": False})
    warning_term = TerminalWizard(io.StringIO(), io.StringIO(), color=False)
    assert wizard._apply_and_show_result(warning_term, state) == 1
    assert "verification reported issues" in warning_term.output.getvalue()
    assert "path warning" in warning_term.output.getvalue()


def test_config_rejects_invalid_shapes_and_modes(tmp_path: Path) -> None:
    from _localsetup.core.config import validate_install_config
    from _localsetup.core.paths import PathValidationError

    with pytest.raises(FileNotFoundError):
        load_install_config(tmp_path / "missing.json")

    invalid_json = tmp_path / "invalid.json"
    invalid_json.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid install config JSON"):
        load_install_config(invalid_json)

    non_object = tmp_path / "list.json"
    non_object.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="install config must be a JSON object"):
        load_install_config(non_object)

    bad_output = tmp_path / "bad-output.json"
    bad_output.write_text('{"output": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="output"):
        load_install_config(bad_output)

    bad_list = tmp_path / "bad-list.json"
    bad_list.write_text('{"platforms": ["codex", ""]}', encoding="utf-8")
    with pytest.raises(ValueError, match="platforms"):
        load_install_config(bad_list)

    bad_string = tmp_path / "bad-string.json"
    bad_string.write_text('{"home": ""}', encoding="utf-8")
    with pytest.raises(ValueError, match="home"):
        load_install_config(bad_string)

    for kwargs, message in [
        ({"attach_mode": "copy"}, "unsupported attach mode"),
        ({"dependency_mode": "magic"}, "unsupported dependency mode"),
        ({"migration_mode": "fast"}, "unsupported migration mode"),
    ]:
        with pytest.raises(ValueError, match=message):
            merge_cli_config(InstallConfig(), **kwargs)
    with pytest.raises(ValueError, match="unsupported backup policy"):
        validate_install_config(InstallConfig(backup_policy="never"))

    with pytest.raises(PathValidationError, match="contains a NUL byte"):
        merge_cli_config(InstallConfig(), home="bad\x00path")


def test_adapter_state_edge_cases_cover_markers_symlinks_and_child_types(tmp_path: Path) -> None:
    from _localsetup.core.adapters import adapter_targets

    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    global_root = home / ".local" / "share" / "localsetup" / "packages"
    global_root.mkdir(parents=True)
    (global_root / "ls-context").mkdir()

    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / ".localsetup-adapter.json").write_text("[]", encoding="utf-8")
    state = apply_mod.adapter_path_state(adapter, global_root)
    assert state["package_integrity_failures"][0]["reason"] == "adapter marker is not a JSON object"

    (adapter / ".localsetup-adapter.json").write_text('{"mode": "symlink"}', encoding="utf-8")
    (adapter / "ls-context").mkdir()
    (adapter / "plain.txt").write_text("plain\n", encoding="utf-8")
    integrity = apply_mod.adapter_path_state(adapter, global_root)["package_integrity_failures"]
    reasons = {row["reason"] for row in integrity}
    assert "symlink adapter package is not a symlink" in reasons
    assert "adapter package is not a supported filesystem node" in reasons

    portable = tmp_path / "portable"
    portable.mkdir()
    (portable / ".localsetup-adapter.json").write_text('{"mode": "portable"}', encoding="utf-8")
    (portable / "ls-context").symlink_to(global_root / "ls-context", target_is_directory=True)
    portable_failures = apply_mod.adapter_path_state(portable, global_root)["package_integrity_failures"]
    assert portable_failures[0]["reason"] == "portable adapter package is not a directory copy"

    symlink_adapter = tmp_path / "symlink-adapter"
    symlink_adapter.symlink_to(Path("missing-global"), target_is_directory=True)
    assert apply_mod.adapter_path_state(symlink_adapter, global_root)["is_dangling_symlink"] is True

    with pytest.raises(ValueError, match="unknown platform selector"):
        adapter_targets(root, home, ["not-a-platform"])


def test_verify_and_rollback_issue_branches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target"
    target.mkdir()
    (target / "_localsetup").mkdir()
    (target / "localsetup.lock.json").write_text("{}", encoding="utf-8")
    global_root = home / ".local" / "share" / "localsetup" / "packages"
    global_root.mkdir(parents=True)
    package = global_root / "ls-context"
    package.mkdir()
    (target / ".localsetup").mkdir()
    (target / ".localsetup" / "lock.json").write_text(
        json.dumps(
            {
                "attach_mode": "portable",
                "aliases": {"context": "missing-skill", "local": "ls-context"},
                "workflows": ["missing-workflow"],
                "installed_skills": [str(package)],
                "adapter_targets": [
                    {"path": str(target / ".codex" / "skills"), "packages": ["ls-context"]},
                    {"path": str(target / ".cursor" / "skills"), "packages": ["ls-context"]},
                    {"path": str(target / ".kilo" / "skills"), "packages": ["ls-context"]},
                ],
            }
        ),
        encoding="utf-8",
    )

    adapters = [
        {
            "platform": "codex",
            "repo_path": str(target / ".codex" / "skills"),
            "exists": False,
            "points_to_global": False,
            "is_scoped_symlink_adapter": False,
            "is_portable_copy": False,
            "visible_packages": [],
            "package_integrity_failures": [],
        },
        {
            "platform": "cursor",
            "repo_path": str(target / ".cursor" / "skills"),
            "exists": True,
            "points_to_global": False,
            "is_scoped_symlink_adapter": False,
            "is_portable_copy": False,
            "visible_packages": [],
            "package_integrity_failures": [],
        },
        {
            "platform": "kilo",
            "repo_path": str(target / ".kilo" / "skills"),
            "exists": True,
            "points_to_global": False,
            "is_scoped_symlink_adapter": False,
            "is_portable_copy": True,
            "visible_packages": ["other"],
            "package_integrity_failures": [{"package": "ls-context"}],
        },
    ]
    monkeypatch.setattr("_localsetup.core.verify.adapter_status", lambda *args, **kwargs: adapters)
    monkeypatch.setattr("_localsetup.core.verify.validate_workflow_catalog", lambda *args, **kwargs: ["bad workflow"])
    monkeypatch.setattr(
        "_localsetup.core.verify.provenance_report",
        lambda *args, **kwargs: {"warnings": [], "repair_hints": []},
    )

    payload = verify_install(root, home, platform_ids=["codex", "cursor", "kilo"], target_root=target)

    assert payload["ok"] is False
    assert any("legacy root lockfile remains" in issue for issue in payload["issues"])
    assert any("stale target framework source" in issue for issue in payload["issues"])
    assert any("missing managed skill" in issue for issue in payload["issues"])
    assert any("managed marker missing" in issue for issue in payload["issues"])
    assert any("missing managed workflow" in issue for issue in payload["issues"])
    assert any("adapter visible packages do not match selection" in issue for issue in payload["issues"])
    assert any("workflow manifest validation failed" in issue for issue in payload["issues"])

    outside_adapter = tmp_path / "outside" / "skills"
    (target / ".localsetup" / "lock.json").write_text(
        json.dumps({"adapter_state": [str(outside_adapter)], "installed_skills": [], "installed_workflows": []}),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="outside target root"):
        rollback(root, home, target_root=target)


def test_schema_reports_missing_file_and_validation_errors(tmp_path: Path) -> None:
    schema = tmp_path / "schema.json"

    assert validate_json_schema({}, schema, label="demo") == []

    schema.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "required": ["name"],
                "properties": {"name": {"type": "string"}},
            }
        ),
        encoding="utf-8",
    )

    issues = validate_json_schema({}, schema, label="demo")
    assert issues
    assert issues[0].startswith("demo schema validation failed at <root>")


def test_wizard_back_help_and_interrupt_branches(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)

    close_term = TerminalWizard(io.StringIO(), io.StringIO(), color=False)
    close_term.input.close = lambda: (_ for _ in ()).throw(OSError("close failed"))  # type: ignore[method-assign]
    close_term.close()

    assert wizard._choice_from_input(Choice("x", "X", "summary", "effect", "best", "tradeoff")).value == "x"
    generic_help = TerminalWizard(io.StringIO(), io.StringIO(), color=False)
    wizard._print_step_help(generic_help, help_text=None, allow_many=True)
    wizard._print_step_help(generic_help, help_text=None, allow_many=False)
    assert "several comma-separated" in generic_help.output.getvalue()
    assert "Enter a number" in generic_help.output.getvalue()

    assert wizard._target_directory_prompt(TerminalWizard(io.StringIO("b\n"), io.StringIO(), color=False)) == wizard.BACK
    choose_many_term = TerminalWizard(io.StringIO("?\nd\ncore\n"), io.StringIO(), color=False)
    assert choose_many(choose_many_term, "Packs", [("core", "Core")], default=[], allow_none=True) == ["core"]
    assert "Enter one number" in choose_many_term.output.getvalue()

    state = wizard.WizardState(repo_root=root, home=tmp_path / "home", caller_directory=root, target_directory=root)
    for step in (
        wizard._pack_step,
        wizard._skill_group_step,
        wizard._skill_individual_step,
        wizard._options_step,
    ):
        assert step(TerminalWizard(io.StringIO("b\n"), io.StringIO(), color=False), state) == wizard.BACK
    state.platforms = ["codex"]
    state.preset = "core"
    assert wizard._platform_step(TerminalWizard(io.StringIO("\nb\n"), io.StringIO(), color=False), state) == wizard.BACK

    interrupted = TerminalWizard(io.StringIO(), io.StringIO(), color=False)
    wizard._write_interrupted_message(interrupted, apply_started=False)
    assert "No changes were applied" in interrupted.output.getvalue()


def test_cli_helper_and_policy_branches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    skill = root / "_localsetup" / "skills" / "ls-context" / "SKILL.md"
    skill.write_text(
        "---\nname: ls-context\nrisk: high\npermissions: bad\n---\n# Context\n",
        encoding="utf-8",
    )

    args = SimpleNamespace(cmd="plan", target_directory=None)
    monkeypatch.setenv(cli_mod.SHIM_ENV, "1")
    monkeypatch.setattr(cli_mod, "detect_invocation_target", lambda: root)
    cli_mod._inject_global_target(args)
    assert args.target_directory == str(root)
    assert cli_mod._target_directory_value(args) == str(root)

    policy = cli_mod._policy_findings(root, ["ls-context"], "ci")
    assert policy["warnings"]
    assert any("high-risk skill blocked" in blocker for blocker in policy["blockers"])

    global_root = home / ".local" / "share" / "localsetup" / "packages"
    global_root.mkdir(parents=True)
    adapter = root / ".codex" / "skills"
    adapter.parent.mkdir(parents=True)
    adapter.symlink_to(global_root, target_is_directory=True)
    assert cli_mod._existing_target_platforms(root, root, home) == [{"platform": "codex", "mode": "symlink"}]

    fake_plan = SimpleNamespace(actions=[], rollback_metadata={"skills": [], "workflows": [], "platforms": [], "global_only": True})
    monkeypatch.setattr(cli_mod, "build_install_plan", lambda *args, **kwargs: fake_plan)
    monkeypatch.setattr(cli_mod, "install_inventory", lambda *args, **kwargs: {})
    monkeypatch.setattr(cli_mod, "_policy_findings", lambda *args, **kwargs: {"mode": "standard", "warnings": ["warn"], "blockers": []})
    assert cli_mod._main(["--source-root", str(root), "--home", str(home), "--target-directory", str(root), "plan"]) == 0
    assert "target directory was provided but no platforms were selected" in capsys.readouterr().out

    monkeypatch.setattr(cli_mod, "_policy_findings", lambda *args, **kwargs: {"mode": "standard", "warnings": [], "blockers": ["block"]})
    assert cli_mod._main(["--source-root", str(root), "--home", str(home), "install", "--apply"]) == 1
    assert "block" in capsys.readouterr().out

    monkeypatch.setattr(cli_mod, "run_doctor", lambda *args, **kwargs: {"ok": True, "warnings": [], "blockers": []})
    monkeypatch.setattr(cli_mod, "shell_registration_status", lambda *args, **kwargs: {"warnings": ["shell warn"]})
    assert cli_mod._main(["--source-root", str(root), "--home", str(home), "doctor"]) == 0
    assert "shell warn" in capsys.readouterr().out


def test_cli_no_command_prints_concise_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli_mod._main([]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "localsetup: command required" in captured.err
    assert "localsetup doctor" in captured.err
    assert "localsetup verify --level filesystem" in captured.err
    assert "the following arguments are required: cmd" not in captured.err


def test_cli_version_failure_branches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    root = make_temp_repo(tmp_path)

    release_type_required = {"ok": False, "release_type_required": True, "bump": "major", "target_version": "9.9.9"}
    monkeypatch.setattr(cli_mod, "plan_version", lambda *args, **kwargs: release_type_required)
    assert cli_mod._main(["--source-root", str(root), "version-sync"]) == 1
    assert "release_type_required" in capsys.readouterr().out
    assert cli_mod._main(["--source-root", str(root), "release-push"]) == 1
    assert "release_type_required" in capsys.readouterr().out

    plans = iter(
        [
            {"ok": False, "release_type_required": False, "bump": "patch", "target_version": "9.9.9"},
            release_type_required,
        ]
    )
    monkeypatch.setattr(cli_mod, "plan_version", lambda *args, **kwargs: next(plans))
    monkeypatch.setattr(cli_mod, "sync_version_files", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(cli_mod, "commit_version_sync", lambda *args, **kwargs: "abc123")
    assert cli_mod._main(["--source-root", str(root), "release-push"]) == 1
    assert "release_type_required" in capsys.readouterr().out


def test_dependency_status_and_ensure_error_branches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from _localsetup.core import dependencies as deps

    root = make_temp_repo(tmp_path)

    monkeypatch.delenv("LOCALSETUP_UV_BIN", raising=False)
    monkeypatch.setattr(deps.shutil, "which", lambda name: None)
    status = deps.dependency_status(root)
    assert status.mode == "prompt-only"
    assert status.ok is False
    assert any("uv is required" in blocker for blocker in status.blockers)

    monkeypatch.setenv("LOCALSETUP_UV_BIN", "uv")

    old_uv_commands: list[list[str]] = []

    def old_uv_runner(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        old_uv_commands.append(cmd)
        if cmd[-1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, "uv 0.4.26\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    old_status = deps.dependency_status(root, runner=old_uv_runner)
    assert old_status.ok is False
    assert old_status.minimum_version == "0.4.27"
    assert any("uv 0.4.26 is too old" in blocker for blocker in old_status.blockers)
    assert old_status.lock_status == "unchecked"
    assert not any(cmd[-2:] == ["lock", "--check"] for cmd in old_uv_commands)

    missing_lock_root = make_temp_repo(tmp_path / "missing-lock")
    (missing_lock_root / "uv.lock").unlink()
    missing_status = deps.dependency_status(missing_lock_root, runner=old_uv_runner)
    assert missing_status.lock_status == "missing"
    assert any("uv.lock not found" in blocker for blocker in missing_status.blockers)

    def stale_runner(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[-1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, "uv 0.11.5\n", "")
        if cmd[-2:] == ["lock", "--check"]:
            return subprocess.CompletedProcess(cmd, 1, "", "lock would change")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    stale_status = deps.dependency_status(root, runner=stale_runner)
    assert stale_status.lock_status == "stale"
    with pytest.raises(RuntimeError, match="uv lockfile is stale"):
        deps.ensure_dependencies(root, mode="uv-sync", runner=stale_runner)

    def fail_sync_runner(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[-1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, "uv 0.11.5\n", "")
        if "sync" in cmd:
            return subprocess.CompletedProcess(cmd, 1, "", "network timed out")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    with pytest.raises(RuntimeError, match="network-or-index"):
        deps.ensure_dependencies(root, mode="uv-sync", runner=fail_sync_runner)

    prompt = deps.ensure_dependencies(root, mode="user-pip", runner=fail_sync_runner)
    assert prompt["mode"] == "prompt-only"
    assert prompt["changed"] is False


def test_path_layout_validation_edge_cases(tmp_path: Path) -> None:
    from _localsetup.core import paths

    for value, message in [
        ("", "must not be empty"),
        ("bad\x00path", "contains a NUL byte"),
        ("C:/Users/demo", "absolute Windows path"),
        ("../escape", "parent path"),
        ("/absolute", "repo-relative"),
        ("~/absolute", "repo-relative"),
    ]:
        with pytest.raises(paths.PathValidationError, match=message):
            paths.validate_repo_relative_path(value)

    with pytest.raises(paths.PathValidationError, match="scoped under the user home"):
        paths.validate_home_scoped_path("relative/path")
    assert str(paths.expand_user_path("~/demo")).endswith("/demo")

    with pytest.raises(paths.PathValidationError, match="must contain _localsetup"):
        paths.source_layout(tmp_path / "not-source")

    source = tmp_path / "source"
    (source / "_localsetup").mkdir(parents=True)
    assert paths.source_layout(source).source_root == source.resolve()
    layout = paths.global_layout(tmp_path / "home", package_root="~/pkg", registry_path="~/registry.json")
    assert layout.package_root == (tmp_path / "home" / "pkg").resolve()
    target = paths.target_layout(tmp_path / "target")
    assert paths.target_lockfile_path(target.target_root).name == "lock.json"
    assert paths.legacy_target_lockfile_path(target.target_root).name == "localsetup.lock.json"
    assert paths.target_journal_root(target.target_root).name == "install-journal"
    assert paths.target_backup_root(target.target_root).name == "backups"


def test_package_helpers_cover_error_and_mismatch_branches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from _localsetup.core import package as pkg

    root = tmp_path / "repo"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname = \"demo\"\ndependencies = [\"plain-package>=1\", \"locked==2.0\"]\n",
        encoding="utf-8",
    )
    lock_text = """
version = 1

[[package]]
name = "localsetup"
version = "1.0.0"
source = { editable = "." }

[[package]]
name = "plain-package"
version = "1.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "locked"
version = "2.0"
source = { registry = "https://pypi.org/simple" }
"""
    (root / "uv.lock").write_text(lock_text, encoding="utf-8")
    artifact = tmp_path / "artifact.tar.gz"
    with tarfile.open(artifact, "w:gz") as tar:
        info = tarfile.TarInfo("uv.lock")
        data = lock_text.encode("utf-8")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))

    assert pkg._components_for_sbom(root)[0]["name"] == "locked"
    assert pkg._expected_components_from_artifact(artifact)
    empty_artifact = tmp_path / "empty.tar.gz"
    with tarfile.open(empty_artifact, "w:gz"):
        pass
    assert pkg._expected_components_from_artifact(empty_artifact) == []

    output = tmp_path / "source.cdx.json"
    fake_pack = SimpleNamespace(pack_id="pack", version=1, lockfile=".localsetup/lock.json")
    monkeypatch.setattr(pkg, "load_pack_config", lambda repo: fake_pack)
    monkeypatch.setattr("_localsetup.core.manifests.load_pack_config", lambda repo: fake_pack)
    assert pkg.write_source_sbom(root, output)["component_count"] == 2

    target = tmp_path / "target"
    (target / ".localsetup").mkdir(parents=True)
    (target / ".localsetup" / "lock.json").write_text(
        json.dumps({"installed_skills": [str(tmp_path / "ls-a")], "installed_workflows": [str(tmp_path / "wf")]}),
        encoding="utf-8",
    )
    assert pkg.write_installed_sbom(root, target, tmp_path / "installed.cdx.json")["component_count"] == 2

    missing_meta = tmp_path / "missing-meta.tar.gz"
    with tarfile.open(missing_meta, "w:gz"):
        pass
    with pytest.raises(ValueError, match="artifact metadata not found"):
        pkg.read_artifact_metadata(missing_meta)

    empty_sha = tmp_path / "empty.sha256"
    empty_sha.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="empty sha256"):
        pkg.parse_sha256_file(empty_sha)
    bad_sha = tmp_path / "bad.sha256"
    bad_sha.write_text("not-a-digest artifact.tar.gz\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid sha256 digest"):
        pkg.parse_sha256_file(bad_sha)

    assert pkg.verify_cyclonedx_sbom(tmp_path / "missing.cdx.json", artifact, {})["ok"] is False
    invalid_sbom = tmp_path / "invalid.cdx.json"
    invalid_sbom.write_text("{", encoding="utf-8")
    assert "invalid SBOM JSON" in pkg.verify_cyclonedx_sbom(invalid_sbom, artifact, {})["error"]

    with pytest.raises(ValueError, match="artifact not found"):
        pkg.verify_release_artifact(tmp_path / "missing.tar.gz")
    with pytest.raises(ValueError, match="sha256 file not found"):
        pkg.verify_release_artifact(artifact)

    metadata = {"schema_version": 1, "artifact": "other.tar.gz", "pack_id": "pack", "version": 1, "source_commit": "abc"}
    with tarfile.open(artifact, "w:gz") as tar:
        meta_bytes = json.dumps(metadata).encode("utf-8")
        meta = tarfile.TarInfo(pkg.ARTIFACT_METADATA_PATH)
        meta.size = len(meta_bytes)
        tar.addfile(meta, io.BytesIO(meta_bytes))
    digest = pkg.sha256_file(artifact)
    sha = artifact.with_name(f"{artifact.name}.sha256")
    sha.write_text(f"{digest}  wrong-name.tar.gz\n", encoding="utf-8")
    sbom = artifact.with_name(f"{artifact.name}.cdx.json")
    sbom.write_text(
        json.dumps(
            {
                "bomFormat": "CycloneDX",
                "metadata": {
                    "component": {"name": "wrong"},
                    "properties": [
                        {"name": "localsetup:artifact", "value": "wrong"},
                        {"name": "localsetup:source_commit", "value": "wrong"},
                    ],
                },
                "components": [],
            }
        ),
        encoding="utf-8",
    )
    result = pkg.verify_release_artifact(artifact, expected_commit="expected", expected_tag="v1")
    assert result["ok"] is False
    assert {check["name"] for check in result["checks"]} >= {
        "sha256_filename",
        "metadata_artifact",
        "source_commit",
        "source_tag",
        "sbom",
    }


def test_versioning_pure_and_check_branches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from _localsetup.core import versioning as ver

    with pytest.raises(ValueError, match="invalid semantic version"):
        ver.SemVer.parse("not-semver")
    with pytest.raises(ValueError, match="unknown bump type"):
        ver.SemVer(1, 2, 3).bump("weird")
    assert ver.classify_commit("Merge branch main") == "none"
    assert ver.classify_commit("Revert something") == "none"
    assert ver.classify_commit("oops") == "patch"
    assert ver.classify_commit_for_release(tmp_path, ver.CommitInfo("a", "Merge branch", "")) == "none"
    assert ver.classify_commit_for_release(tmp_path, ver.CommitInfo("b", "Revert thing", "")) == "none"
    assert ver.release_type_override("Release-Type: Minor") == "minor"
    assert ver.version_from_sync_commit(ver.VERSION_SYNC_PREFIX) is None
    assert ver.version_from_sync_commit(f"{ver.VERSION_SYNC_PREFIX} nope") is None
    remaining, canceled = ver.net_unreleased_commits(
        [
            ver.CommitInfo("1", "feat: add thing", ""),
            ver.CommitInfo("2", 'Revert "missing"', ""),
            ver.CommitInfo("3", 'Revert "feat: add thing"', ""),
        ]
    )
    assert [commit.sha for commit in remaining] == ["2"]
    assert canceled[0]["original_sha"] == "1"

    def fake_run_git(repo_root: Path, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        if args[0] == "log":
            return subprocess.CompletedProcess(args, 0, "bad-record\x1eabc\x1fsubject\x1fbody\x1e", "")
        if args[:2] == ["rev-parse", "--verify"]:
            return subprocess.CompletedProcess(args, 1, "", "")
        if args[:2] == ["symbolic-ref", "--quiet"]:
            return subprocess.CompletedProcess(args, 1, "", "")
        if args[:2] == ["remote", "show"]:
            return subprocess.CompletedProcess(args, 0, "  HEAD branch: main\n", "")
        if args[0] == "merge-base":
            return subprocess.CompletedProcess(args, 0, "merge-sha\n", "")
        if args[0] == "diff":
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(args, 0, "head-sha\n", "")

    monkeypatch.setattr(ver, "_run_git", fake_run_git)
    assert ver.list_commits(tmp_path, "base", "base") == []
    assert len(ver.list_commits(tmp_path, "base", "head")) == 1
    assert ver._symbolic_remote_head(tmp_path, "origin") == "origin/main"
    with pytest.raises(ValueError, match="explicit base ref did not resolve"):
        ver.resolve_base_with_metadata(tmp_path, base="missing", head="head")

    (tmp_path / "VERSION").write_text("1.2.3\n", encoding="utf-8")
    (tmp_path / "_localsetup" / "docs").mkdir(parents=True)
    monkeypatch.setattr(ver, "_git_text", lambda *args, **kwargs: "")

    def sync_creates_file(repo_root: Path, target_version: str) -> dict:
        (repo_root / "pyproject.toml").write_text(target_version, encoding="utf-8")
        (repo_root / "VERSION").write_text(target_version, encoding="utf-8")
        return {"ok": True}

    monkeypatch.setattr(ver, "sync_version_files", sync_creates_file)
    check = ver.check_version_files(tmp_path, "2.0.0")
    assert check["ok"] is True
    assert not (tmp_path / "pyproject.toml").exists()
    assert (tmp_path / "VERSION").read_text(encoding="utf-8") == "1.2.3\n"

    monkeypatch.setattr(ver, "plan_version", lambda *args, **kwargs: {"ok": True})
    plans = ver.push_lines_to_plans(
        tmp_path,
        "\ninvalid line\nrefs/heads/main " + ver.ZERO_SHA + " refs/heads/main abc\nrefs/heads/main local refs/heads/main remote\n",
    )
    assert plans == [{"ok": True}]

    monkeypatch.setattr(ver, "stage_version_files", lambda repo_root: None)
    monkeypatch.setattr(ver, "_git_text", lambda repo_root, args: "" if args[:2] == ["diff", "--cached"] else "head-sha")
    assert ver.commit_version_sync(tmp_path, "2.0.0") is None


def test_provenance_edge_cases_and_report_warnings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from _localsetup.core import provenance as prov

    root = tmp_path / "repo"
    root.mkdir()
    (root / "VERSION").write_text("1.2.3\n", encoding="utf-8")

    responses = {
        ("rev-parse", "HEAD^{tree}"): subprocess.CompletedProcess([], 0, "tree-sha\n", ""),
        ("status", "--porcelain", "--untracked-files=all"): subprocess.CompletedProcess(
            [],
            0,
            " M _localsetup/docs/_generated/facts.json\nR  assets/README.md -> _localsetup/docs/SKILLS.md\n",
            "",
        ),
        ("log", "-1", "--pretty=%s"): subprocess.CompletedProcess([], 0, "docs: refresh generated artifacts\n", ""),
        ("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"): subprocess.CompletedProcess(
            [], 0, "_localsetup/docs/_generated/facts.json\n", ""
        ),
        ("rev-parse", "HEAD^"): subprocess.CompletedProcess([], 0, "parent-sha\n", ""),
        ("describe", "--tags", "--exact-match", "parent-sha"): subprocess.CompletedProcess([], 1, "", ""),
        ("rev-parse", "parent-sha^{tree}"): subprocess.CompletedProcess([], 0, "parent-tree\n", ""),
        ("config", "--get", "remote.origin.url"): subprocess.CompletedProcess(
            [], 0, "git@github.com:CruxExperts/localsetup.git\n", ""
        ),
    }

    def fake_run_git(repo_root: Path, args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return responses.get(tuple(args), subprocess.CompletedProcess(args, 1, "", "fail"))

    monkeypatch.setattr(prov, "run_git", fake_run_git)
    monkeypatch.setattr(prov, "source_commit", lambda repo: "head-sha")
    monkeypatch.setattr(prov, "source_tag", lambda repo: "v1")

    assert prov._status_entry_paths("??") == []
    assert prov._status_entry_paths("R  old -> new") == ["old", "new"]
    assert prov.source_dirty(root) is False
    assert prov.generated_artifact_parent_source_commit(root) == "parent-sha"
    base = prov.base_provenance(root, emitter="docs", generated_at=True, generated_commit_parent=True)
    assert base["source_commit"] == "parent-sha"
    assert base["source_tree_sha"] == "parent-tree"
    assert base["source_remote_url"] if "source_remote_url" in base else True
    assert prov.source_remote_url(root) == "https://github.com/CruxExperts/localsetup"
    assert prov.framework_version(tmp_path / "missing") == "unknown"

    package = tmp_path / "package"
    package.mkdir()
    (package / prov.MARKER_LEGACY).write_text("legacy marker\n", encoding="utf-8")
    assert prov.has_legacy_marker(package) is True
    assert prov.load_package_marker(package)["legacy_marker"] is True
    assert prov.marker_public_snapshot(None) is None

    rendered = prov.markdown_with_provenance(
        "---\ntitle: Old\nlocalsetup_provenance:\n  old: value\nframework_version: old\nsource_commit: old\nartifact_sha256: old\n---\n\nBody\n",
        base,
    )
    assert "title: Old" in rendered
    assert "old: value" not in rendered
    assert rendered.endswith("Body\n")
    assert "provenance" in prov.json_with_provenance({"a": 1}, base)

    content_path = root / "artifact.txt"
    content_path.write_text("artifact\n", encoding="utf-8")
    entry = prov.artifact_registry_entry(root, content_path, artifact_type="text", emitter="test")
    assert entry["path"] == "artifact.txt"

    global_root = tmp_path / "global"
    global_root.mkdir()
    stale = global_root / "ls-stale"
    stale.mkdir()
    (stale / "file.txt").write_text("current\n", encoding="utf-8")
    markerless = global_root / "ls-markerless"
    markerless.mkdir()
    legacy = global_root / "ls-legacy"
    legacy.mkdir()
    (legacy / prov.MARKER_LEGACY).write_text("legacy\n", encoding="utf-8")
    portable_global = global_root / "ls-portable"
    portable_global.mkdir()
    (portable_global / "SKILL.md").write_text("global\n", encoding="utf-8")

    portable_adapter = tmp_path / "portable-adapter"
    portable_pkg = portable_adapter / "ls-portable"
    portable_pkg.mkdir(parents=True)
    (portable_pkg / "SKILL.md").write_text("local drift\n", encoding="utf-8")
    registry_dir = root / "_localsetup" / "docs" / "_generated"
    registry_dir.mkdir(parents=True)
    (registry_dir / "artifact-registry.json").write_text(
        json.dumps({"artifacts": [{"path": "missing.txt"}, {"path": "artifact.txt", "artifact_sha256": "wrong"}]}),
        encoding="utf-8",
    )

    report = prov.provenance_report(
        root,
        lock={
            "package_provenance": {
                "ls-stale": {"package_digest": "old"},
                "ls-missing": {"package_digest": "old"},
            }
        },
        registry={"packages": {"ls-stale": {"digest": "registry-old"}}},
        global_root=global_root,
        adapters=[
            {"repo_path": str(tmp_path / "global-adapter"), "points_to_global": True},
            {
                "repo_path": str(portable_adapter),
                "is_portable_copy": True,
                "package_integrity_failures": [],
            },
            {
                "repo_path": str(tmp_path / "scoped"),
                "is_scoped_symlink_adapter": True,
                "visible_packages": ["ls-context"],
                "expected_packages": ["ls-context", "ls-extra"],
                "package_integrity_failures": [{"package": None, "reason": "bad marker"}],
            },
            {"repo_path": str(tmp_path / "unmanaged"), "exists": True, "package_integrity_failures": []},
        ],
    )

    joined = "\n".join(report["warnings"])
    assert "target lock references stale package digest" in joined
    assert "target lock references missing global package digest" in joined
    assert "global registry digest differs" in joined
    assert "legacy plain managed marker" in joined
    assert "managed package marker missing" in joined
    assert "portable adapter package differs" in joined
    assert "scoped adapter package set differs" in joined
    assert "generated artifact missing" in joined
    assert "generated artifact has stale content digest" in joined


def test_harness_helpers_error_and_cron_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from _localsetup.core import harness

    repo = tmp_path / "repo"
    target = tmp_path / "target"
    repo.mkdir()
    target.mkdir()

    monkeypatch.setattr(harness.importlib.util, "spec_from_file_location", lambda *args, **kwargs: None)
    with pytest.raises(RuntimeError, match="unable to load heartbeat runtime"):
        harness._load_runtime(repo)

    missing = target / "missing.yaml"
    assert harness._read_yaml(missing) == {}
    empty = target / "empty.yaml"
    empty.write_text("", encoding="utf-8")
    assert harness._read_yaml(empty) == {}
    bad = target / "bad.yaml"
    bad.write_text("- nope\n", encoding="utf-8")
    with pytest.raises(ValueError, match="YAML root must be a mapping"):
        harness._read_yaml(bad)

    existing = target / "existing.txt"
    existing.write_text("old", encoding="utf-8")
    assert harness._write_text_if_missing(existing, "new") is False
    with pytest.raises(ValueError, match="range 1..1440"):
        harness._interval_schedule(0)
    assert harness._interval_schedule(60) == "0 */1 * * *"

    monkeypatch.setattr(harness.shutil, "which", lambda name: "/usr/bin/localsetup")
    assert harness._heartbeat_command(repo, target)[0] == "/usr/bin/localsetup"
    monkeypatch.setattr(harness.shutil, "which", lambda name: None)
    assert harness._heartbeat_command(repo, target)[0] == sys.executable

    monkeypatch.setattr(harness, "validate_cron_manifest", lambda *args, **kwargs: None)
    cron = harness._upsert_cron_manifest(
        repo,
        target,
        {"heartbeat": {"interval_minutes": 30}},
        enabled=True,
    )
    assert cron["summary"]["task"]["enabled"] is True
    cron = harness._upsert_cron_manifest(
        repo,
        target,
        {"heartbeat": {"interval_minutes": 30}},
        enabled=False,
    )
    assert cron["summary"]["task"]["enabled"] is False

    with pytest.raises(RuntimeError, match="requires --install-crontab and --yes"):
        harness._install_live_crontab(repo, target, yes=False)

    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if cmd[0] == "crontab":
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(harness.subprocess, "run", fake_run)
    assert harness._install_live_crontab(repo, target, yes=True)["installed"] is True
    assert calls[-1][0] == "crontab"

    (target / harness.HEARTBEAT_CONFIG).parent.mkdir(parents=True, exist_ok=True)
    (target / harness.HEARTBEAT_CONFIG).write_text("heartbeat: bad\n", encoding="utf-8")
    with pytest.raises(ValueError, match="heartbeat config must be a mapping"):
        harness.enable(repo, target)
    assert harness.payload_to_text({"ok": True}).startswith("{")


def test_repo_finalizer_helpers_and_run_branches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from _localsetup.core import repo_finalizer as rf

    repo = tmp_path / "repo"
    repo.mkdir()
    config = repo / "config" / "localsetup_finalizer.yaml"
    config.parent.mkdir()
    config.write_text("- bad\n", encoding="utf-8")
    with pytest.raises(ValueError, match="finalizer config must be a mapping"):
        rf._read_config(repo)

    config.write_text("managed_output_globs: [123]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="managed_output_globs"):
        rf._settings(repo)

    settings = rf.FinalizerSettings(
        managed_output_globs=["managed/**"],
        generated_artifact_globs=["generated/**"],
        runtime_ignored_globs=[".state", ".state/**"],
        stage_allowlist_globs=["managed/**", "generated/**"],
    )
    items = [
        {"path": "managed/file", "status": " M", "tracked": True, "deleted": False, "renamed_or_copied": False},
        {"path": "generated/file", "status": "??", "tracked": False, "deleted": False, "renamed_or_copied": False},
        {"path": ".state/log", "status": "!!", "tracked": False, "ignored": True, "deleted": False, "renamed_or_copied": False},
        {"path": "_localsetup/file", "status": " M", "tracked": True, "deleted": False, "renamed_or_copied": False},
        {"path": "README.md", "status": " M", "tracked": True, "deleted": False, "renamed_or_copied": False},
        {"path": "copy.txt", "status": "R ", "tracked": True, "deleted": False, "renamed_or_copied": True},
        {"path": "gone.txt", "status": " D", "tracked": True, "deleted": True, "renamed_or_copied": False},
        {"path": "_localsetup", "status": "??", "tracked": False, "deleted": False, "renamed_or_copied": False},
    ]
    classified = rf._classify(repo, items, settings, mode="target")
    categories = {row["path"]: row["classification"] for row in classified}
    assert categories["managed/file"] == "managed_output"
    assert categories["generated/file"] == "generated_artifact"
    assert categories[".state/log"] == "runtime_ignored"
    assert categories["_localsetup"] == "stale_legacy_framework_source"
    assert any(row["renamed_or_copied"] for row in classified)
    assert any(row["deleted"] for row in classified)

    assert rf._runtime_roots(["", ".state/**", "logs/*.json"]) == [".state", "logs"]

    def unsupported_git(target_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        if args[:2] == ["rev-parse", "--is-inside-work-tree"]:
            return subprocess.CompletedProcess(args, 1, "", "not git")
        if args[:2] == ["rev-parse", "--git-path"]:
            return subprocess.CompletedProcess(args, 0, ".git/info/exclude\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(rf, "_git", unsupported_git)
    unsupported = rf.run(repo)
    assert unsupported["report_only"] is True
    assert "report_paths" in unsupported

    monkeypatch.setattr(rf, "_snapshot", lambda *args, **kwargs: {"git_supported": True, "target_root": str(repo), "files": [], "actions": [], "state_dir": str(repo / rf.STATE_DIR), "summary": {}})
    no_commit = rf.run(repo, no_commit=True)
    assert no_commit["took_action"] is False
    with pytest.raises(ValueError, match="--checkpoint requires --message"):
        rf.run(repo, checkpoint=True)

    staged_payload = {
        "git_supported": True,
        "target_root": str(repo),
        "files": [{"path": "managed/file", "planned_action": "stage", "blocker": False}],
        "actions": [],
        "state_dir": str(repo / rf.STATE_DIR),
        "summary": {},
    }
    monkeypatch.setattr(rf, "_snapshot", lambda *args, **kwargs: dict(staged_payload))

    def git_add_fail(target_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        if args[0] == "add":
            return subprocess.CompletedProcess(args, 1, "", "add failed")
        if args[:2] == ["rev-parse", "--git-path"]:
            return subprocess.CompletedProcess(args, 0, ".git/info/exclude\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(rf, "_git", git_add_fail)
    with pytest.raises(RuntimeError, match="add failed"):
        rf.run(repo)

    def git_commit_fail(target_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        if args[0] == "add":
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[0] == "commit":
            return subprocess.CompletedProcess(args, 1, "", "commit failed")
        if args[:2] == ["rev-parse", "--git-path"]:
            return subprocess.CompletedProcess(args, 0, ".git/info/exclude\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(rf, "_git", git_commit_fail)
    with pytest.raises(RuntimeError, match="commit failed"):
        rf.run(repo, checkpoint=True, message="checkpoint")

    text = rf.payload_to_text({"mode": "run", "target_root": str(repo), "git_supported": True, "status": "blocked", "summary": {"total_dirty_files": 1, "blockers": 1, "stage_candidates": 0}, "files": classified[:1], "actions": [{"kind": "evaluate"}]})
    assert "actions:" in text
