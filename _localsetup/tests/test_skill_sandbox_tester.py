import importlib.util
from pathlib import Path

from _localsetup.v3.manifests import load_platforms


def load_create_sandbox_module():
    root = Path(__file__).resolve().parents[2]
    script = root / "_localsetup" / "skills" / "ls-skill-sandbox-tester" / "scripts" / "create_sandbox.py"
    spec = importlib.util.spec_from_file_location("ls_skill_sandbox_create_sandbox", script)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_skill_root_subpaths_follow_platform_manifest() -> None:
    root = Path(__file__).resolve().parents[2]
    module = load_create_sandbox_module()
    platform_roots = {
        repo_path
        for platform in load_platforms(root)
        for repo_path in platform.repo_paths
    }

    assert set(module.SKILL_ROOT_SUBPATHS) == {"_localsetup/skills", *platform_roots}
    assert "skills" not in module.SKILL_ROOT_SUBPATHS
    assert ".agents/skills" not in module.SKILL_ROOT_SUBPATHS


def test_resolves_skill_name_from_framework_source(monkeypatch) -> None:
    root = Path(__file__).resolve().parents[2]
    module = load_create_sandbox_module()

    monkeypatch.chdir(root)

    resolved = module._resolve_skill_dir_by_name("ls-skill-creator", None)
    assert resolved == root / "_localsetup" / "skills" / "ls-skill-creator"


def test_resolves_skill_name_from_adapter_root(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    adapter_skill = repo / ".codex" / "skills" / "ls-demo"
    adapter_skill.mkdir(parents=True)
    (adapter_skill / "SKILL.md").write_text(
        "---\nname: ls-demo\ndescription: Demo.\n---\n",
        encoding="utf-8",
    )
    module = load_create_sandbox_module()

    monkeypatch.chdir(repo)

    resolved = module._resolve_skill_dir_by_name("ls-demo", None)
    assert resolved == adapter_skill
