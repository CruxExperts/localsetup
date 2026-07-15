from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "create_sandbox.py"


def load_create_sandbox():
    spec = importlib.util.spec_from_file_location("create_sandbox", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def make_skill(root: Path, name: str) -> Path:
    skill_dir = root / "ls" / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: test skill\n---\n", encoding="utf-8"
    )
    return skill_dir


def test_resolve_skill_name_from_repo_root_and_skill_dir(monkeypatch, tmp_path: Path) -> None:
    create_sandbox = load_create_sandbox()
    target = make_skill(tmp_path, "ls-example-skill")
    runner_skill = make_skill(tmp_path, "ls-skill-sandbox-tester")

    monkeypatch.chdir(tmp_path)
    assert create_sandbox._resolve_skill_dir_by_name("ls-example-skill", None) == target

    monkeypatch.chdir(runner_skill)
    assert create_sandbox._resolve_skill_dir_by_name("ls-example-skill", None) == target


@pytest.mark.parametrize("name", ["Ls-Example", "ls_example", "-ls-example", "ls-example-", "ls--example"])
def test_sanitize_skill_name_rejects_nonstandard_names(name: str) -> None:
    create_sandbox = load_create_sandbox()

    with pytest.raises(ValueError, match="lowercase letters, numbers, and single hyphens"):
        create_sandbox._sanitize_skill_name(name)


def test_sanitize_skill_name_accepts_repo_standard_name() -> None:
    create_sandbox = load_create_sandbox()

    assert create_sandbox._sanitize_skill_name("ls-example-skill") == "ls-example-skill"
