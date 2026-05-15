import subprocess
from pathlib import Path

from _localsetup.v3.provenance import (
    MARKER_LEGACY,
    build_package_marker,
    load_package_marker,
    source_dirty,
    source_tag,
)
from _localsetup.v3.lockfile import save_json


def run(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    return completed.stdout.strip()


def make_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    run(repo, "init", "-q")
    run(repo, "config", "user.email", "test@example.invalid")
    run(repo, "config", "user.name", "Test User")
    (repo / "VERSION").write_text("3.9.0\n", encoding="utf-8")
    package = repo / "_localsetup" / "skills" / "ls-demo"
    package.mkdir(parents=True)
    (package / "SKILL.md").write_text("---\nname: ls-demo\n---\n", encoding="utf-8")
    run(repo, "add", ".")
    run(repo, "commit", "-q", "-m", "chore: initial")
    return repo


def test_provenance_payload_clean_dirty_and_tagged_git_state(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path)
    package = repo / "_localsetup" / "skills" / "ls-demo"

    clean_marker = build_package_marker(
        repo,
        package,
        package_name="ls-demo",
        package_type="skill",
        source_path=package,
        emitter="test",
        installed_at=False,
    )
    assert clean_marker["framework_version"] == "3.9.0"
    assert clean_marker["source_dirty"] is False
    assert clean_marker["source_tag"] is None
    assert clean_marker["source_tree_sha"]
    assert clean_marker["package_digest"]
    assert clean_marker["source_provenance_hash"]

    run(repo, "tag", "v3.9.0")
    assert source_tag(repo) == "v3.9.0"
    tagged_marker = build_package_marker(
        repo,
        package,
        package_name="ls-demo",
        package_type="skill",
        source_path=package,
        emitter="test",
        installed_at=False,
    )
    assert tagged_marker["source_tag"] == "v3.9.0"

    (package / "SKILL.md").write_text("---\nname: ls-demo\ndescription: Dirty\n---\n", encoding="utf-8")
    assert source_dirty(repo) is True
    dirty_marker = build_package_marker(
        repo,
        package,
        package_name="ls-demo",
        package_type="skill",
        source_path=package,
        emitter="test",
        installed_at=False,
    )
    assert dirty_marker["source_dirty"] is True


def test_source_dirty_includes_untracked_package_sources(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path)
    package = repo / "_localsetup" / "skills" / "ls-demo"
    (package / "UNTRACKED.txt").write_text("included in copy\n", encoding="utf-8")

    marker = build_package_marker(
        repo,
        package,
        package_name="ls-demo",
        package_type="skill",
        source_path=package,
        emitter="test",
        installed_at=False,
    )

    assert marker["source_dirty"] is True


def test_source_dirty_ignores_generated_doc_outputs(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path)
    generated_files = [
        repo / "_localsetup" / "docs" / "SKILLS.md",
        repo / "_localsetup" / "docs" / "WORKFLOW_REGISTRY.md",
        repo / "_localsetup" / "docs" / "_generated" / "facts.json",
        repo / "_localsetup" / "docs" / "_generated" / "skill-taxonomy.json",
        repo / "_localsetup" / "docs" / "migration" / "v2-to-v3-skill-map.md",
        repo / "assets" / "README.md",
    ]
    for path in generated_files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("generated\n", encoding="utf-8")

    assert source_dirty(repo) is False

    (repo / "VERSION").write_text("3.9.1\n", encoding="utf-8")

    assert source_dirty(repo) is True


def test_package_marker_loads_json_and_legacy_text(tmp_path: Path) -> None:
    package = tmp_path / "ls-demo"
    package.mkdir()
    save_json(package / ".localsetup-managed.json", {"schema_version": 1, "package_name": "ls-demo"})
    assert load_package_marker(package)["package_name"] == "ls-demo"

    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / MARKER_LEGACY).write_text("source=localsetup-context\n", encoding="utf-8")
    marker = load_package_marker(legacy)
    assert marker["schema_version"] == 0
    assert marker["legacy_marker"] is True
    assert marker["source"] == "source=localsetup-context"
