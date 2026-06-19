from __future__ import annotations

from _localsetup.tests.test_install_flow import *

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


def test_doctor_repair_modern_deployment_dry_run_has_no_actions(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target"
    target.mkdir()
    plan = build_install_plan(root, home=home, packs=["core"], platform_ids=["codex"], target_root=target)
    apply_plan(root, plan, home=home, target_root=target)

    report = run_repair(root, home=home, target_root=target)

    assert report["ok"] is True
    assert report["applied"] is False
    assert report["actions"] == []
    assert report["decisions"] == []


def test_doctor_repair_apply_noops_when_no_actions(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target"
    target.mkdir()
    plan = build_install_plan(root, home=home, packs=["core"], platform_ids=["codex"], target_root=target)
    apply_plan(root, plan, home=home, target_root=target)
    lock_before = (target / ".localsetup" / "lock.json").read_text(encoding="utf-8")

    report = run_repair(root, home=home, target_root=target, apply=True)

    assert report["ok"] is True
    assert report["applied"] is False
    assert report["actions"] == []
    assert (target / ".localsetup" / "lock.json").read_text(encoding="utf-8") == lock_before


def test_doctor_repair_converts_legacy_lockfile(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "legacy-target"
    target.mkdir()
    legacy_lock = target / "localsetup.lock.json"
    legacy_lock.write_text(
        json.dumps({"platforms": ["codex"], "repo_packages": ["localsetup-context"]}) + "\n",
        encoding="utf-8",
    )

    dry = run_repair(root, home=home, target_root=target)
    assert dry["applied"] is False
    assert legacy_lock.exists()
    report = run_repair(root, home=home, target_root=target, apply=True)
    lock = load_json(target / ".localsetup" / "lock.json")

    assert any(action["kind"] == "backup_remove_legacy_lock" for action in dry["actions"])
    assert report["ok"] is True
    assert report["applied"] is True
    assert not legacy_lock.exists()
    assert (target / ".localsetup" / "lock.json").is_file()
    assert Path(lock["migration_origin"]["backup"]).is_file()
    assert report["verify"]["ok"] is True


def test_doctor_repair_preserves_framework_shaped_content_that_differs_from_source(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target"
    stale = target / "_localsetup"
    (stale / "config").mkdir(parents=True)
    (stale / "core").mkdir()
    (stale / "config" / "pack.yaml").write_text("old: true\n", encoding="utf-8")

    report = run_repair(root, home=home, target_root=target, platform_ids=["codex"], apply=True)

    assert report["ok"] is False
    assert report["applied"] is False
    assert stale.exists()
    assert report["detected_shape"]["stale_framework"]["classification"] == "custom_localsetup_content"
    assert "config/pack.yaml" in report["detected_shape"]["stale_framework"]["modified_entries"]
    assert any(item.get("code") == "custom_localsetup_content" for item in report["decisions"])


def test_doctor_repair_protects_maintainer_source_checkout(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "maintainer"
    shutil.copytree(root, target)

    report = run_repair(root, home=home, target_root=target, platform_ids=["codex"], apply=True)

    assert report["ok"] is False
    assert report["applied"] is False
    assert any(decision["kind"] == "protected_source_root" for decision in report["decisions"])
    assert (target / "_localsetup" / "config" / "pack.yaml").is_file()
    assert not (target / ".localsetup" / "lock.json").exists()


def test_doctor_repair_protects_managed_source_checkout_path(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    managed_source = home / ".local" / "share" / "localsetup" / "source"
    shutil.copytree(root, managed_source)

    report = run_repair(root, home=home, target_root=managed_source, platform_ids=["codex"], apply=True)

    assert report["ok"] is False
    assert report["applied"] is False
    assert "default managed Localsetup source checkout" in report["detected_shape"]["protected_reasons"]
    assert any(decision["kind"] == "protected_source_root" for decision in report["decisions"])
    assert (managed_source / "_localsetup" / "core").is_dir()
    assert not (managed_source / ".localsetup" / "lock.json").exists()


def test_doctor_repair_protects_registered_custom_source_checkout(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    registered_source = tmp_path / "custom-source"
    shutil.copytree(root, registered_source)
    register_shell_command(registered_source, home=home)

    report = run_repair(root, home=home, target_root=registered_source, platform_ids=["codex"], apply=True)

    assert report["ok"] is False
    assert report["applied"] is False
    assert "registered Localsetup shell source checkout" in report["detected_shape"]["protected_reasons"]
    assert any(decision["kind"] == "protected_source_root" for decision in report["decisions"])
    assert (registered_source / "_localsetup" / "tools" / "localsetup.py").is_file()
    assert not (registered_source / ".localsetup" / "lock.json").exists()


def test_doctor_repair_blocks_nonempty_plan_for_protected_source_checkout(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "maintainer"
    shutil.copytree(root, target)
    (target / "localsetup.lock.json").write_text('{"platforms": ["codex"]}\n', encoding="utf-8")

    report = run_repair(root, home=home, target_root=target, apply=True)

    assert report["ok"] is False
    assert report["applied"] is False
    assert any(action["kind"] == "backup_remove_legacy_lock" for action in report["actions"])
    assert any(decision["kind"] == "protected_source_root" for decision in report["decisions"])
    assert (target / "localsetup.lock.json").is_file()
    assert not (target / ".localsetup" / "lock.json").exists()


def test_doctor_repair_retires_old_agents_codex_adapter(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target"
    old_adapter = target / ".agents" / "skills"
    old_adapter.mkdir(parents=True)
    (old_adapter / "localsetup-context").mkdir()
    (old_adapter / "localsetup-context" / "SKILL.md").write_text("---\nname: localsetup-context\n---\n", encoding="utf-8")

    dry = run_repair(root, home=home, target_root=target)
    report = run_repair(root, home=home, target_root=target, apply=True)

    assert dry["inferred"]["platforms"] == ["codex"]
    assert not any(action["kind"] == "backup_remove_historical_adapter" for action in dry["actions"])
    assert any(decision["kind"] == "adapter_content" for decision in dry["decisions"])
    assert report["applied"] is False
    assert old_adapter.exists()


def test_doctor_repair_unmanaged_adapter_content_requires_decision(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target"
    collision = target / ".codex" / "skills"
    collision.mkdir(parents=True)
    (collision / "custom.txt").write_text("user content\n", encoding="utf-8")

    report = run_repair(root, home=home, target_root=target, platform_ids=["codex"], apply=True)

    assert report["ok"] is False
    assert report["applied"] is False
    assert report["decisions"]
    assert (collision / "custom.txt").is_file()
    assert not (target / ".localsetup" / "lock.json").exists()


def test_doctor_repair_custom_skill_directory_preserves_content(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target"
    adapter = target / ".codex" / "skills"
    custom = adapter / "media-batch-ops"
    custom.mkdir(parents=True)
    (custom / "SKILL.md").write_text("# Custom repo skill\n", encoding="utf-8")

    report = run_repair(root, home=home, target_root=target, platform_ids=["codex"], apply=True)

    assert report["ok"] is True
    assert report["applied"] is True
    assert report["decisions"] == []
    assert (custom / "SKILL.md").read_text(encoding="utf-8") == "# Custom repo skill\n"
    assert (adapter / "ls-context").is_symlink()


def test_doctor_repair_repo_local_symlink_adapter_preserves_target(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target"
    historical = target / ".agents" / "skills"
    custom = historical / "fleetctl"
    custom.mkdir(parents=True)
    (custom / "SKILL.md").write_text("# Fleet custom skill\n", encoding="utf-8")
    adapter = target / ".codex" / "skills"
    adapter.parent.mkdir(parents=True)
    adapter.symlink_to(Path("..") / ".agents" / "skills", target_is_directory=True)

    report = run_repair(root, home=home, target_root=target, platform_ids=["codex"], apply=True)

    assert report["ok"] is True
    assert report["applied"] is True
    assert report["decisions"] == []
    assert (custom / "SKILL.md").read_text(encoding="utf-8") == "# Fleet custom skill\n"
    assert adapter.is_symlink()
    assert (historical / "ls-context").is_symlink()

    refreshed = run_repair(root, home=home, target_root=target, platform_ids=["codex"], apply=True)
    assert refreshed["ok"] is True
    assert refreshed["decisions"] == []


def test_doctor_repair_broken_adapter_symlink_is_recreated(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target"
    adapter = target / ".codex" / "skills"
    adapter.parent.mkdir(parents=True)
    adapter.symlink_to(target / "missing-global", target_is_directory=True)

    report = run_repair(root, home=home, target_root=target, platform_ids=["codex"], apply=True)

    assert report["ok"] is False
    assert any(decision["kind"] == "adapter_collision" for decision in report["decisions"])
    assert adapter.is_symlink()
    assert report["verify"] is None


def test_doctor_repair_recreates_dangling_managed_root_adapter_symlink(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target"
    global_root = home / ".local" / "share" / "localsetup" / "packages"
    adapter = target / ".codex" / "skills"
    adapter.parent.mkdir(parents=True)
    adapter.symlink_to(global_root / "missing-adapter-root", target_is_directory=True)

    report = run_repair(root, home=home, target_root=target, platform_ids=["codex"], apply=True)

    assert report["ok"] is True
    assert not adapter.is_symlink()
    assert_scoped_adapter(adapter, "ls-context")
    assert report["verify"]["ok"] is True


def test_doctor_repair_dry_run_never_mutates_repo(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target"
    target.mkdir()
    legacy_lock = target / "localsetup.lock.json"
    legacy_lock.write_text('{"platforms": ["codex"]}\n', encoding="utf-8")

    report = run_repair(root, home=home, target_root=target)

    assert report["applied"] is False
    assert legacy_lock.is_file()
    assert not (target / ".localsetup").exists()
    assert not (target / ".codex").exists()


def test_doctor_repair_cli_subcommand_applies(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target"
    target.mkdir()
    (target / "localsetup.lock.json").write_text('{"platforms": ["codex"]}\n', encoding="utf-8")
    tool = root / "_localsetup" / "tools" / "localsetup.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(tool),
            "--repo",
            str(root),
            "--home",
            str(home),
            "doctor",
            "repair",
            "--target-directory",
            str(target),
            "--yes",
        ],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    payload = json.loads(completed.stdout)

    assert payload["ok"] is True
    assert payload["applied"] is True
    assert (target / ".localsetup" / "lock.json").is_file()
    assert (target / ".codex" / "skills" / ".localsetup-adapter.json").is_file()
