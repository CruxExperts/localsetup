from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "create_sandbox.py"


def load_create_sandbox():
    spec = importlib.util.spec_from_file_location("create_sandbox", SCRIPT_PATH)
    assert spec is not None
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


def test_explicit_skills_root_precedes_framework_environment(monkeypatch, tmp_path: Path) -> None:
    create_sandbox = load_create_sandbox()
    framework_skill = make_skill(tmp_path / "framework", "ls-example-skill")
    explicit_skill = make_skill(tmp_path / "explicit", "ls-example-skill")
    monkeypatch.setenv("LOCALSETUP_FRAMEWORK_DIR", str(framework_skill.parents[2]))

    resolved = create_sandbox._resolve_skill_dir_by_name(
        "ls-example-skill", explicit_skill.parent
    )

    assert resolved == explicit_skill


@pytest.mark.parametrize("environment_suffix", [Path(), Path("ls")])
def test_framework_environment_accepts_repo_or_ls_directory(
    environment_suffix: Path, monkeypatch, tmp_path: Path
) -> None:
    create_sandbox = load_create_sandbox()
    repo = tmp_path / "framework"
    target = make_skill(repo, "ls-example-skill")
    monkeypatch.setenv("LOCALSETUP_FRAMEWORK_DIR", str(repo / environment_suffix))
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)

    assert create_sandbox._resolve_skill_dir_by_name("ls-example-skill", None) == target


@pytest.mark.parametrize("name", ["Ls-Example", "ls_example", "-ls-example", "ls-example-", "ls--example"])
def test_sanitize_skill_name_rejects_nonstandard_names(name: str) -> None:
    create_sandbox = load_create_sandbox()

    with pytest.raises(ValueError, match="lowercase letters, numbers, and single hyphens"):
        create_sandbox._sanitize_skill_name(name)


def test_sanitize_skill_name_accepts_repo_standard_name() -> None:
    create_sandbox = load_create_sandbox()

    assert create_sandbox._sanitize_skill_name("ls-example-skill") == "ls-example-skill"


def test_main_creates_marked_copy_within_platform_temp(
    monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    create_sandbox = load_create_sandbox()
    source = make_skill(tmp_path / "source", "ls-example-skill")
    temp_root = tmp_path / "approved-temp"
    temp_root.mkdir()
    monkeypatch.setattr(create_sandbox.tempfile, "gettempdir", lambda: str(temp_root))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "create_sandbox.py",
            "--skill-path",
            str(source),
            "--base-dir",
            str(temp_root),
        ],
    )

    assert create_sandbox.main() == 0

    skill_copy = Path(capsys.readouterr().out.strip())
    marker_path = skill_copy.parent / create_sandbox.MARKER_NAME
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert skill_copy.parent.parent == temp_root
    assert marker == {
        "schema_version": create_sandbox.MARKER_SCHEMA_VERSION,
        "sandbox_dir": str(skill_copy.resolve()),
        "skill_name": source.name,
        "source_dir": str(source.resolve()),
    }
    assert (skill_copy / "SKILL.md").is_file()


def test_base_dir_must_remain_within_platform_temp(monkeypatch, tmp_path: Path) -> None:
    create_sandbox = load_create_sandbox()
    temp_root = tmp_path / "approved-temp"
    outside = tmp_path / "outside"
    temp_root.mkdir()
    outside.mkdir()
    monkeypatch.setattr(create_sandbox.tempfile, "gettempdir", lambda: str(temp_root))

    with pytest.raises(ValueError, match="within platform temp root"):
        create_sandbox._validate_base_dir(outside)


def test_create_sandbox_rejects_source_symlinks(tmp_path: Path) -> None:
    create_sandbox = load_create_sandbox()
    source = make_skill(tmp_path / "source", "ls-example-skill")
    outside = tmp_path / "outside.py"
    outside.write_text("print('outside')\n", encoding="utf-8")
    (source / "linked.py").symlink_to(outside)

    with pytest.raises(ValueError, match="contains a symlink"):
        create_sandbox._create_sandbox(source, tmp_path)
