from __future__ import annotations

from _localsetup.tests.test_install_flow import *

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
        (adapter / "ls-context").write_text("user content\n", encoding="utf-8")
        expected = "adapter contains custom or unknown entries with selected Localsetup package names"
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
    collision.parent.mkdir(parents=True)
    collision.write_text("not a directory\n", encoding="utf-8")

    global_only = run_doctor(root, home=home)
    selected = run_doctor(root, home=home, platform_ids=["cursor"])

    assert global_only["adapter_collisions"] == []
    assert not any("adapter collision" in blocker for blocker in global_only["blockers"])
    assert selected["ok"] is False
    assert selected["adapter_collisions"][0]["reason"] == "regular file"


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


def test_plugin_list_reports_malformed_manifest_without_traceback(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    manifest = root / "_localsetup" / "config" / "plugin-packs.yaml"
    manifest.write_text(
        """
schema_version: 1
plugin_packs:
  - id: localsetup-broken
    source_pack: bootstrap
    category: broken
    platforms:
      codex:
        interface: v1
    extra_context_inputs: []
""",
        encoding="utf-8",
    )

    code = cli_mod._main(["--source-root", str(root), "--home", str(home), "plugin", "list", "--platform", "codex"])
    output = capsys.readouterr()

    assert code == 1
    payload = json.loads(output.out)
    assert payload["ok"] is False
    assert payload["plugin_packs"] == []
    assert "Traceback" not in output.err
    assert any("plugin-packs.yaml" in issue for issue in payload["issues"])


def test_cli_csv_selector_normalization() -> None:
    assert _split_csv(["codex,kilo", "cursor"]) == ["codex", "kilo", "cursor"]
    assert _split_csv(None) is None
