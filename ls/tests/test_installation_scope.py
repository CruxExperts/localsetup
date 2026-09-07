import json
import pytest
from ls.core.installation_ownership import resolve_skill_scope
from ls.core.plan import build_install_plan
from ls.core.apply_preflight import preflight_install_plan
from ls.tests.test_install_flow import make_temp_repo


def test_scope_inheritance_and_explicit_override(tmp_path):
    assert resolve_skill_scope(tmp_path, None) == "repo"
    legacy = tmp_path / "localsetup.lock.json"
    legacy.write_text(json.dumps({"skill_scope": "personal"}))
    assert resolve_skill_scope(tmp_path, None) == "personal"
    modern = tmp_path / ".localsetup" / "lock.json"
    modern.parent.mkdir(); modern.write_text(json.dumps({"skill_scope": "both"}))
    assert resolve_skill_scope(tmp_path, None) == "both"
    assert resolve_skill_scope(tmp_path, "repo") == "repo"
    modern.write_text("{}")
    assert resolve_skill_scope(tmp_path, None) == "repo"
    for value in ([], "invalid", None):
        modern.write_text(json.dumps({"skill_scope": value}))
        with pytest.raises(ValueError):resolve_skill_scope(tmp_path, None)


@pytest.mark.parametrize("scope", ["repo", "personal", "both"])
def test_scope_plans_only_selected_clients(tmp_path, scope):
    root = make_temp_repo(tmp_path);home = tmp_path / "home"
    plan = build_install_plan(root, home, packs=["core"], platform_ids=["codex", "openclaw"], skill_scope=scope)
    repo = [a for a in plan.actions if a.kind == "attach_repo_path"]
    personal = [a for a in plan.actions if a.kind == "attach_personal_path"]
    assert bool(repo) == (scope != "personal")
    assert bool(personal) == (scope != "repo")
    assert len({a.path for a in personal}) == len(personal)
    assert {owner["client"] for a in personal for owner in a.details["owners"]} == ({"codex", "openclaw"} if personal else set())
    assert all(owner["scope"] == "personal" and owner["root"] == str(home.resolve()) for a in personal for owner in a.details["owners"])
    assert plan.rollback_metadata["skill_scope"] == scope
    if personal:
        preflight = preflight_install_plan(root, plan, home, target_root=root)
        assert preflight["ok"], preflight
    empty = build_install_plan(root, home, packs=["core"], skill_scope=scope)
    assert not any(a.kind in {"attach_repo_path", "attach_personal_path"} for a in empty.actions)
    assert not home.exists() and not (root / ".localsetup" / "lock.json").exists()
