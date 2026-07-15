from __future__ import annotations

from ls.tests.test_install_flow import *

def test_legacy_managed_global_symlink_is_migrated_to_scoped_adapter(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    legacy_root = home / ".local/share/agents/skills/localsetup"
    legacy_root.mkdir(parents=True)
    legacy_adapter = root / ".codex" / "skills"
    legacy_adapter.parent.mkdir(parents=True)
    legacy_adapter.symlink_to(legacy_root, target_is_directory=True)

    apply_plan(root, build_install_plan(root, home=home, packs=["core"], platform_ids=["codex"]), home=home)

    adapter = root / ".agents" / "skills"
    assert_scoped_adapter(adapter, "ls-context")
    assert not legacy_adapter.exists()
    verified = verify_install(root, home, platform_ids=["codex"])
    assert verified["ok"] is True
    assert verified["legacy_codex_transition"]["managed_exposure"] is False


def test_legacy_codex_transition_preserves_mixed_custom_content(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    global_root = home / ".local" / "share" / "localsetup" / "packages"
    managed = global_root / "ls-context"
    legacy = root / ".codex" / "skills"
    legacy.mkdir(parents=True)
    (legacy / "ls-context").symlink_to(managed, target_is_directory=True)
    custom = legacy / "custom-skill"
    custom.mkdir()
    (custom / "SKILL.md").write_text("---\nname: custom-skill\n---\n", encoding="utf-8")
    (legacy / ".localsetup-adapter.json").write_text(
        json.dumps({"version": 1, "mode": "symlink", "packages": ["ls-context"]}) + "\n",
        encoding="utf-8",
    )

    apply_plan(root, build_install_plan(root, home=home, packs=["core"], platform_ids=["codex"]), home=home)

    assert (legacy / "custom-skill" / "SKILL.md").is_file()
    assert not (legacy / "ls-context").exists()
    assert not (legacy / ".localsetup-adapter.json").exists()
    assert_scoped_adapter(root / ".agents" / "skills", "ls-context")
    lock = load_json(root / ".localsetup" / "lock.json")
    assert lock["adapter_transitions"][0]["disposition"] == "retired-managed-entries"

    rollback(root, home)
    assert (legacy / "custom-skill" / "SKILL.md").is_file()
    assert not (root / ".agents" / "skills" / "ls-context").exists()


def test_unproven_legacy_codex_symlink_blocks_before_any_mutation(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    unrelated = tmp_path / "unrelated-skills"
    unrelated.mkdir()
    legacy = root / ".codex" / "skills"
    legacy.parent.mkdir(parents=True)
    legacy.symlink_to(unrelated, target_is_directory=True)
    plan = build_install_plan(root, home=home, packs=["core"], platform_ids=["codex"])

    with pytest.raises(RuntimeError, match="unproven_legacy_codex_symlink"):
        apply_plan(root, plan, home=home, dry_run=False)

    assert legacy.is_symlink()
    assert legacy.resolve(strict=False) == unrelated.resolve(strict=False)
    assert not (root / ".agents" / "skills").exists()
    assert not (root / ".localsetup" / "lock.json").exists()
    assert not (root / ".localsetup" / "install-journal").exists()


def test_recorded_legacy_path_does_not_authorize_replaced_unrelated_symlink(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    legacy = root / ".codex" / "skills"
    legacy.parent.mkdir(parents=True)
    lock = root / ".localsetup" / "lock.json"
    lock.parent.mkdir(parents=True)
    original_lock = json.dumps(
        {
            "platforms": ["codex"],
            "adapter_state": [str(legacy)],
            "adapter_targets": [{"platform": "codex", "path": str(legacy), "packages": ["ls-context"]}],
        },
        sort_keys=True,
    ) + "\n"
    lock.write_text(original_lock, encoding="utf-8")
    unrelated = tmp_path / "replacement-skills"
    unrelated.mkdir()
    legacy.symlink_to(unrelated, target_is_directory=True)
    plan = build_install_plan(root, home=home, packs=["core"], platform_ids=["codex"])

    with pytest.raises(RuntimeError, match="unproven_legacy_codex_symlink"):
        apply_plan(root, plan, home=home, dry_run=False)

    assert legacy.is_symlink()
    assert legacy.resolve(strict=False) == unrelated.resolve(strict=False)
    assert lock.read_text(encoding="utf-8") == original_lock
    assert not (root / ".agents" / "skills").exists()
    assert not (root / ".localsetup" / "install-journal").exists()


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
    adapter = root / ".agents" / "skills"
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
    assert_scoped_adapter(root / ".agents" / "skills", "ls-context")
    assert not (root / ".kilo" / "skills").exists()
    assert not (root / ".cursor" / "skills").exists()
    verify = verify_install(root, home, platform_ids=["codex"])
    assert verify["ok"] is True
    assert {adapter["platform"] for adapter in verify["adapters"]} == {"codex"}

    with pytest.raises(ValueError, match="platform-scoped rollback"):
        rollback(root, home, platform_ids=["codex"])


def test_adapters_accepts_explicit_json_flag_with_platform_filter(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)

    apply_plan(
        root,
        build_install_plan(root, home=home, packs=["core"], platform_ids=["codex"]),
        home=home,
    )

    code = cli_mod._main(
        [
            "--source-root",
            str(root),
            "--home",
            str(home),
            "adapters",
            "--json",
            "--platforms",
            "codex",
        ]
    )
    output = capsys.readouterr().out

    assert code == 0
    payload = json.loads(output)
    assert {adapter["platform"] for adapter in payload} == {"codex"}


def test_adapters_check_reports_codex_adapter_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)

    apply_plan(
        root,
        build_install_plan(root, home=home, packs=["core"], platform_ids=["codex"]),
        home=home,
    )

    code = cli_mod._main(
        [
            "--source-root",
            str(root),
            "--home",
            str(home),
            "adapters",
            "check",
            "--platforms",
            "codex",
        ]
    )
    output = capsys.readouterr().out

    assert code == 0
    payload = json.loads(output)
    assert payload["ok"] is True
    assert "codex" in payload["summary"]["platforms"]
    assert "ls-context" in payload["summary"]["managed_packages"]
    assert {adapter["platform"] for adapter in payload["adapters"]} == {"codex"}
    assert "ls-context" in payload["adapters"][0]["visible_packages"]
    assert "ls-context" in payload["adapters"][0]["managed_visible_packages"]
    assert any(command["command"] == "localsetup verify --tools codex" for command in payload["commands"])


def test_adapters_check_reports_tampered_adapter_without_mutating_custom_content(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)

    apply_plan(
        root,
        build_install_plan(root, home=home, packs=["core"], platform_ids=["codex"]),
        home=home,
    )
    adapter = root / ".agents" / "skills"
    custom = adapter / "custom-skill"
    custom.mkdir()
    (custom / "SKILL.md").write_text("# Custom\n", encoding="utf-8")
    (adapter / "ls-context").unlink()

    code = cli_mod._main(
        [
            "--source-root",
            str(root),
            "--home",
            str(home),
            "adapters",
            "check",
            "--platforms",
            "codex",
        ]
    )
    output = capsys.readouterr().out

    assert code == 1
    payload = json.loads(output)
    assert payload["ok"] is False
    assert payload["issues"]
    assert payload["repair_hints"]
    assert any(command["command"] == "localsetup doctor repair --tools codex" for command in payload["commands"])
    assert (custom / "SKILL.md").read_text(encoding="utf-8") == "# Custom\n"


def test_multi_platform_selector_attaches_only_requested_adapters(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)

    plan = build_install_plan(root, home=home, packs=["core"], platform_ids=["codex", "kilo"])
    result = apply_plan(root, plan, home=home, dry_run=False)
    verify = verify_install(root, home)

    assert result["dry_run"] is False
    assert {Path(adapter["repo_path"]).parent.name for adapter in verify["adapters"]} == {".agents", ".kilo"}
    assert {adapter["platform"] for adapter in verify["adapters"]} == {"codex", "kilo"}
    assert_scoped_adapter(root / ".agents" / "skills", "ls-context")
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
            str(root / "ls" / "tools" / "localsetup.py"),
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
            str(root / "ls" / "tools" / "localsetup.py"),
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
    tool = root / "ls" / "tools" / "localsetup.py"

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
    tool = root / "ls" / "tools" / "localsetup.py"

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
    source = Path(__file__).resolve().parents[1]
    shutil.copytree(source / "lib", root / "ls/lib")
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
    shared_helper = home / ".local/share/localsetup/lib/deps.py"
    assert shared_helper.is_file()

    rollback(root, home=home, target_root=target_one)
    assert managed_skill.is_dir()
    assert shared_helper.is_file()
    rollback(root, home=home, target_root=target_two)
    assert not managed_skill.exists()
    assert not shared_helper.exists()


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


def test_package_prune_skips_hidden_backup_artifacts(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    package_root = home / ".local/share/localsetup/packages"

    apply_plan(
        root,
        build_install_plan(root, home=home, global_packs=["dev"], repo_packs=["dev"], platform_ids=["codex"]),
        home=home,
    )
    backup_artifact = package_root / ".ls-context.localsetup-backup-seeded"
    backup_artifact.mkdir()
    (backup_artifact / ".localsetup-managed.json").write_text("{}\n", encoding="utf-8")

    apply_plan(
        root,
        build_install_plan(root, home=home, global_packs=["core"], repo_packs=["core"], platform_ids=["codex"]),
        home=home,
    )

    assert backup_artifact.is_dir()
    assert not list(package_root.glob("..ls-context.localsetup-backup-*.localsetup-backup-*"))


def test_rollback_cleanup_skips_hidden_backup_artifacts(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    package_root = home / ".local/share/localsetup/packages"

    apply_plan(root, build_install_plan(root, home=home, packs=["core"], platform_ids=["codex"]), home=home)
    backup_artifact = package_root / ".ls-context.localsetup-backup-seeded"
    backup_artifact.mkdir()
    (backup_artifact / ".localsetup-managed.json").write_text("{}\n", encoding="utf-8")

    rollback(root, home=home)

    assert backup_artifact.is_dir()


def test_provenance_report_cli_is_report_only(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    apply_plan(root, build_install_plan(root, home=home, packs=["core"], platform_ids=["codex"]), home=home)

    completed = subprocess.run(
        [
            sys.executable,
            "ls/tools/localsetup.py",
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
            str(root / "ls/tools/localsetup.py"),
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
    assert payload["adapters"][0]["repo_path"] == str(target / ".agents" / "skills")


def test_detach_removes_adapters_and_preserves_packages(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    tool = root / "ls" / "tools" / "localsetup.py"
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
    assert not (root / ".agents" / "skills").exists()
    assert (home / ".local/share/localsetup/packages/ls-context").is_dir()
