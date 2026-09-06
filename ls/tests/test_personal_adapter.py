import json
from pathlib import Path
import pytest
from ls.core.apply import apply_plan
from ls.core.plan import build_install_plan
from ls.core.apply_preflight import preflight_install_plan
from ls.core.registry import load_registry
from ls.tests.test_install_flow import make_temp_repo


def test_personal_shared_owners_and_failed_write_preserve_neighbors(tmp_path, monkeypatch):
    import ls.core.personal_adapter as writer
    root = make_temp_repo(tmp_path);home = tmp_path / "home"
    def plan(client, skill):
        return build_install_plan(root, home, skills=[skill], platform_ids=[client], skill_scope="personal")
    apply_plan(root, plan("cursor", "ls-context"), home)
    shared = home / ".agents" / "skills"
    (shared / "custom.txt").write_text("original")
    # Resolve the actual registry path from the receipt rather than assume its name.
    lock = json.loads((root / ".localsetup/lock.json").read_text())
    registry = Path(lock["registry_path"])
    before = registry.read_bytes()
    save = writer.save_json
    def fail(path, value):
        (shared / "new-custom.txt").write_text("arrived during operation")
        raise RuntimeError("injected marker failure")
    monkeypatch.setattr(writer, "save_json", fail)
    with pytest.raises(RuntimeError, match="injected"):
        apply_plan(root, plan("openclaw", "ls-git-workflows"), home)
    assert registry.read_bytes() == before
    assert (shared / "ls-context").is_symlink()
    assert not (shared / "ls-git-workflows").exists()
    assert (shared / "custom.txt").read_text() == "original"
    assert (shared / "new-custom.txt").read_text() == "arrived during operation"
    monkeypatch.setattr(writer, "save_json", save)
    apply_plan(root, plan("openclaw", "ls-git-workflows"), home)
    assert (shared / "ls-context").is_symlink() and (shared / "ls-git-workflows").is_symlink()
    value = load_registry(registry)
    assert {r["owner"]["client"] for r in value["personal_owners"].values()} == {"cursor", "openclaw"}
    lock = json.loads((root / ".localsetup/lock.json").read_text())
    assert lock["skill_scope"] == "personal" and lock["adapter_targets"] == [] and lock["adapter_state"] == []
    assert lock["personal_adapter_targets"]
    assert not (root / ".agents/skills").exists()


@pytest.mark.parametrize("unsafe", ["ancestor", "collision", "portable"])
def test_personal_preflight_refuses_unsafe_targets(tmp_path, unsafe):
    root = make_temp_repo(tmp_path);home = tmp_path / "home";home.mkdir()
    plan = build_install_plan(root, home, skills=["ls-context"], platform_ids=["cursor"], skill_scope="personal",
                              attach_mode="portable" if unsafe == "portable" else "symlink")
    if unsafe == "ancestor":
        outside = tmp_path / "outside";outside.mkdir();(home / ".agents").symlink_to(outside, target_is_directory=True)
    elif unsafe == "collision":
        custom = home / ".agents/skills/ls-context";custom.mkdir(parents=True);(custom / "SKILL.md").write_text("custom")
    result = preflight_install_plan(root, plan, home, target_root=root)
    assert not result["ok"] and any(b["status_code"] == "personal_adapter_unsafe" for b in result["blockers"])
    assert not (root / ".localsetup/lock.json").exists()


def test_personal_apply_preserves_overlapping_legacy_repository_owner(tmp_path):
    root = make_temp_repo(tmp_path);home = tmp_path / "home"
    repo_plan = build_install_plan(root, home, skills=["ls-context"], platform_ids=["cursor"], target_root=home)
    apply_plan(root, repo_plan, home, target_root=home)
    lock = json.loads((home / ".localsetup/lock.json").read_text())
    registry_path = Path(lock["registry_path"]);registry = load_registry(registry_path)
    for adapter in registry["targets"][str(home.resolve())]["adapters"]:
        adapter.pop("owners", None)
    registry_path.write_text(json.dumps(registry))
    personal = build_install_plan(root, home, skills=["ls-git-workflows"], platform_ids=["openclaw"], skill_scope="personal")
    apply_plan(root, personal, home)
    shared = home / ".agents/skills"
    assert (shared / "ls-context").is_symlink() and (shared / "ls-git-workflows").is_symlink()

    from ls.core.detach import detach_platforms
    from ls.core.rollback import rollback
    before = registry_path.read_bytes()
    for remove in (lambda: detach_platforms(root, home, home, ["cursor"]),
                   lambda: rollback(root, home, target_root=home)):
        with pytest.raises(ValueError, match="overlaps personal"):
            remove()
        assert registry_path.read_bytes() == before
        assert (shared / "ls-context").is_symlink() and (shared / "ls-git-workflows").is_symlink()
    both = build_install_plan(root, home, skills=["ls-context"], platform_ids=["cursor"], target_root=home, skill_scope="both")
    result = preflight_install_plan(root, both, home, target_root=home)
    assert any(b["status_code"] == "overlapping_scope_actions" for b in result["blockers"])

    with pytest.raises(RuntimeError, match="personal_owner_overlap"):
        apply_plan(root, repo_plan, home, target_root=home)
    assert registry_path.read_bytes() == before
    assert (shared / "ls-context").is_symlink() and (shared / "ls-git-workflows").is_symlink()
