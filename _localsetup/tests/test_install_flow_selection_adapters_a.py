from __future__ import annotations

from _localsetup.tests.test_install_flow import *

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
    assert marker["transform_manifest_digest"]
    assert marker["artifact_path"] == str(home / ".local/share/localsetup/packages/ls-context")
    assert marker["marker_path"] == str(home / ".local/share/localsetup/packages/ls-context" / MARKER_JSON)
    assert (home / ".local/share/localsetup/packages/ls-context/references/localsetup/.localsetup-reference-bundle.json").is_file()
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


def test_core_installs_tmux_workflow_packages(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)

    plan = build_install_plan(root, home=home, packs=["core"], platform_ids=["codex"])
    workflow_action = next(a for a in plan.actions if a.kind == "install_workflows")

    assert "ls-workflow-ops-tmux-session" in workflow_action.details["workflows"]
    assert "ls-workflow-tmux-terminal-mode" in workflow_action.details["workflows"]

    apply_plan(root, plan, home=home, dry_run=False)
    lock = load_json(root / ".localsetup/lock.json")
    global_root = home / ".local/share/localsetup/packages"

    assert (global_root / "ls-workflow-ops-tmux-session" / "SKILL.md").is_file()
    assert (global_root / "ls-workflow-tmux-terminal-mode" / "workflow.yaml").is_file()
    assert "ls-workflow-ops-tmux-session" in lock["workflows"]
    assert "ls-workflow-tmux-terminal-mode" in lock["workflows"]
    verify = verify_install(root, home, platform_ids=["codex"])
    doctor = run_doctor(root, home=home, platform_ids=["codex"])
    assert verify["ok"] is True
    assert verify["tmux_terminal_mode"]["workflows"]["lock_present"] == [
        "ls-workflow-ops-tmux-session",
        "ls-workflow-tmux-terminal-mode",
    ]
    assert verify["tmux_terminal_mode"]["workflows"]["adapters"][0]["missing_workflows"] == []
    assert doctor["tmux_terminal_mode"]["workflows"]["adapters"][0]["missing_workflows"] == []


def test_codex_platform_installs_guardian_subagent(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"

    plan = build_install_plan(root, home=home, packs=["core"], platform_ids=["codex"])
    agent_action = next(a for a in plan.actions if a.kind == "install_codex_agents")
    assert agent_action.path == home / ".codex" / "agents"
    assert agent_action.details["agents"] == ["guardian_subagent"]

    result = apply_plan(root, plan, home=home)
    agent_path = home / ".codex" / "agents" / "guardian_subagent.toml"
    lock = load_json(root / ".localsetup/lock.json")
    text = agent_path.read_text(encoding="utf-8")

    assert agent_path.is_file()
    assert 'model = "gpt-5.5"' in text
    assert 'model_reasoning_effort = "low"' in text
    assert str(agent_path) in result["installed_codex_agents"]
    assert str(agent_path) in lock["installed_codex_agents"]
    assert lock["codex_agents"] == ["guardian_subagent"]


def test_codex_agent_conflict_blocks_overwrite(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    agent_path = home / ".codex" / "agents" / "guardian_subagent.toml"
    agent_path.parent.mkdir(parents=True)
    agent_path.write_text("name = \"guardian_subagent\"\nmodel = \"custom\"\n", encoding="utf-8")

    plan = build_install_plan(root, home=home, packs=["core"], platform_ids=["codex"])

    with pytest.raises(RuntimeError, match="codex_agent_conflict"):
        apply_plan(root, plan, home=home)

    assert agent_path.read_text(encoding="utf-8") == "name = \"guardian_subagent\"\nmodel = \"custom\"\n"


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
