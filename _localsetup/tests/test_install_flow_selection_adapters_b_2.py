from __future__ import annotations

from _localsetup.tests.test_install_flow import *

def test_detach_preserves_custom_adapter_entries(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    tool = root / "_localsetup" / "tools" / "localsetup.py"
    apply_plan(
        root,
        build_install_plan(
            root,
            home=home,
            global_packs=["core"],
            repo_preset="custom",
            repo_skills=["localsetup-context"],
            platform_ids=["codex"],
        ),
        home=home,
    )
    custom = root / ".codex" / "skills" / "custom-skill"
    custom.mkdir()
    (custom / "SKILL.md").write_text("# Custom\n", encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(tool), "--repo", str(root), "--home", str(home), "detach", "--tools", "codex"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert (custom / "SKILL.md").read_text(encoding="utf-8") == "# Custom\n"
    assert not (root / ".codex" / "skills" / "ls-context").exists()
    assert not (root / ".codex" / "skills" / ".localsetup-adapter.json").exists()
    assert (home / ".local/share/localsetup/packages/ls-context").is_dir()


def test_detach_legacy_portable_adapter_removes_managed_entries_only(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    tool = root / "_localsetup" / "tools" / "localsetup.py"
    global_root = home / ".local" / "share" / "localsetup" / "packages"
    managed = global_root / "ls-context"
    managed.mkdir(parents=True)
    (managed / MARKER_JSON).write_text("{}\n", encoding="utf-8")
    adapter = root / ".codex" / "skills"
    adapter.mkdir(parents=True)
    (adapter / ".localsetup-portable").write_text("managed_by=localsetup\n", encoding="utf-8")
    shutil.copytree(managed, adapter / "ls-context")
    custom = adapter / "custom-skill"
    custom.mkdir()
    (custom / "SKILL.md").write_text("# Custom\n", encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(tool), "--repo", str(root), "--home", str(home), "detach", "--tools", "codex"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert not (adapter / "ls-context").exists()
    assert not (adapter / ".localsetup-portable").exists()
    assert (custom / "SKILL.md").read_text(encoding="utf-8") == "# Custom\n"
