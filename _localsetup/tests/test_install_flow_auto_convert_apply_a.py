from __future__ import annotations

from _localsetup.tests.test_install_flow import *

def test_no_selector_plan_install_and_update_infer_existing_modern_repo(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target"
    target.mkdir()
    plan = build_install_plan(
        root,
        home=home,
        global_preset="suggested",
        repo_preset="custom",
        repo_skills=["ls-context"],
        platform_ids=["codex"],
        target_root=target,
    )
    apply_plan(root, plan, home=home, target_root=target)

    planned = run_localsetup_cli(root, home, "plan", "--target-directory", str(target))
    assert planned.returncode == 0, planned.stderr
    plan_payload = json.loads(planned.stdout)
    assert plan_payload["auto_mode"] == "inferred_existing"
    assert plan_payload["attachment"]["platforms"] == ["codex"]
    assert plan_payload["rollback"]["repo_packages"] == [
        "ls-context",
        "ls-workflow-ops-tmux-session",
        "ls-workflow-tmux-terminal-mode",
    ]

    installed = run_localsetup_cli(root, home, "install", "--target-directory", str(target), "--apply")
    assert installed.returncode == 0, installed.stderr
    install_payload = json.loads(installed.stdout)
    assert install_payload["auto_mode"] == "inferred_existing"
    assert_scoped_adapter(target / ".codex" / "skills", "ls-context")

    updated = run_localsetup_cli(root, home, "update", "--target-directory", str(target))
    assert updated.returncode == 0, updated.stderr
    update_payload = json.loads(updated.stdout)
    lock = load_json(target / ".localsetup" / "lock.json")
    assert update_payload["auto_mode"] == "inferred_existing"
    assert lock["platforms"] == ["codex"]
    assert lock["repo_packages"] == [
        "ls-context",
        "ls-workflow-ops-tmux-session",
        "ls-workflow-tmux-terminal-mode",
    ]
    assert lock["global_baseline_selectors"]["preset"] == "suggested"


def test_no_selector_install_repairs_legacy_lockfile(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "legacy-target"
    target.mkdir()
    (target / "localsetup.lock.json").write_text(
        json.dumps({"platforms": ["codex"], "repo_packages": ["localsetup-context"]}) + "\n",
        encoding="utf-8",
    )

    completed = run_localsetup_cli(root, home, "install", "--target-directory", str(target), "--apply")
    payload = json.loads(completed.stdout)

    assert completed.returncode == 0, completed.stderr
    assert payload["auto_mode"] == "repair_required"
    assert payload["applied"] is True
    assert not (target / "localsetup.lock.json").exists()
    assert (target / ".localsetup" / "lock.json").is_file()
    assert_scoped_adapter(target / ".codex" / "skills", "ls-context")


def test_no_selector_update_requires_decision_for_unknown_broken_adapter(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target"
    target.mkdir()
    adapter = target / ".codex" / "skills"
    adapter.parent.mkdir(parents=True)
    adapter.symlink_to(target / "missing-global", target_is_directory=True)

    completed = run_localsetup_cli(root, home, "update", "--target-directory", str(target))
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1, completed.stderr
    assert payload["auto_mode"] == "repair_required"
    assert payload["applied"] is False
    assert any(decision["kind"] == "adapter_collision" for decision in payload["decisions"])
    assert adapter.is_symlink()


def test_no_selector_install_preserves_benign_adapter_file(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target"
    collision = target / ".codex" / "skills"
    collision.mkdir(parents=True)
    (collision / "custom.txt").write_text("user content\n", encoding="utf-8")

    completed = run_localsetup_cli(root, home, "install", "--target-directory", str(target), "--apply")
    payload = json.loads(completed.stdout)

    assert completed.returncode == 0, completed.stderr
    assert payload["auto_mode"] == "repair_required"
    assert payload["decisions"] == []
    assert (collision / "custom.txt").is_file()
    assert_scoped_adapter(collision, "ls-context")
    assert (target / ".localsetup" / "lock.json").exists()


def test_no_selector_install_new_repo_uses_normal_global_without_adapters(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "new-target"
    (target / ".github" / "workflows").mkdir(parents=True)
    (target / ".github" / "workflows" / "ci.yml").write_text("name: ci\n", encoding="utf-8")
    (target / "package.json").write_text("{}", encoding="utf-8")

    completed = run_localsetup_cli(root, home, "install", "--target-directory", str(target), "--apply")
    payload = json.loads(completed.stdout)
    lock = load_json(target / ".localsetup" / "lock.json")

    assert completed.returncode == 0, completed.stderr
    assert payload["auto_mode"] == "default_new_repo"
    assert lock["global_only"] is True
    assert lock["platforms"] == []
    assert lock["repo_packages"] == []
    assert lock["global_baseline_selectors"]["preset"] == "normal"
    assert lock["global_baseline_packs"] == [
        "bootstrap",
        "core",
        "dev",
        "frontend",
        "architecture",
        "ops",
        "publishing",
    ]
    assert "publishing" in lock["global_baseline_packs"]
    assert "ls-nodejs-nextjs" in lock["global_baseline_packages"]
    assert not (target / ".codex" / "skills").exists()


def test_explicit_selectors_bypass_no_selector_auto_mode(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target"
    target.mkdir()

    completed = run_localsetup_cli(
        root,
        home,
        "install",
        "--target-directory",
        str(target),
        "--platforms",
        "codex",
        "--apply",
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 0, completed.stderr
    assert payload["auto_mode"] == "explicit"
    assert payload["attachment"]["platforms"] == ["codex"]
    assert_scoped_adapter(target / ".codex" / "skills", "ls-context")


def test_no_selector_install_protected_source_checkout_allows_safe_refresh(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "maintainer"
    shutil.copytree(root, target)
    adapter = target / ".codex" / "skills"
    adapter.mkdir(parents=True)
    (adapter / "README.md").write_text("repo note\n", encoding="utf-8")

    completed = run_localsetup_cli(root, home, "install", "--target-directory", str(target), "--apply")
    payload = json.loads(completed.stdout)

    assert completed.returncode == 0, completed.stderr
    assert payload["auto_mode"] == "repair_required"
    assert payload["decisions"] == []
    assert (target / "_localsetup" / "config" / "pack.yaml").is_file()
    assert (adapter / "README.md").is_file()
    assert_scoped_adapter(adapter, "ls-context")
    assert (target / ".localsetup" / "lock.json").exists()


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
