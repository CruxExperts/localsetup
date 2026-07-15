import os
import subprocess
from pathlib import Path

from ls.core.baseline import tracked_files
from ls.core.git_subprocess import GIT_ENV_TO_SCRUB
from ls.core.provenance import (
    MARKER_LEGACY,
    base_provenance,
    build_package_marker,
    load_package_marker,
    source_dirty,
    source_remote_url,
    source_tag,
)
from ls.core.lockfile import save_json


def clean_git_env(**overrides: str) -> dict[str, str]:
    env = os.environ.copy()
    for name in GIT_ENV_TO_SCRUB:
        env.pop(name, None)
    env.update(overrides)
    return env


def run(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=clean_git_env(),
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
    (repo / "VERSION").write_text("4.9.0\n", encoding="utf-8")
    package = repo / "ls" / "skills" / "ls-demo"
    package.mkdir(parents=True)
    (package / "SKILL.md").write_text("---\nname: ls-demo\n---\n", encoding="utf-8")
    run(repo, "add", ".")
    run(repo, "commit", "-q", "-m", "chore: initial")
    return repo


def make_poison_index(tmp_path: Path) -> tuple[Path, Path]:
    alien = tmp_path / "alien"
    alien.mkdir()
    run(alien, "init", "-q")
    plugin_file = alien / ".agents" / "plugins" / "marketplace.json"
    plugin_file.parent.mkdir(parents=True)
    plugin_file.write_text('{"name": "plugin-marketplace"}\n', encoding="utf-8")
    poison_index = tmp_path / "poison.index"
    subprocess.run(
        ["git", "add", "-A"],
        cwd=alien,
        env=clean_git_env(GIT_INDEX_FILE=str(poison_index)),
        text=True,
        capture_output=True,
        check=True,
    )
    return poison_index, alien


def test_provenance_payload_clean_dirty_and_tagged_git_state(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path)
    package = repo / "ls" / "skills" / "ls-demo"

    clean_marker = build_package_marker(
        repo,
        package,
        package_name="ls-demo",
        package_type="skill",
        source_path=package,
        emitter="test",
        installed_at=False,
    )
    assert clean_marker["framework_version"] == "4.9.0"
    assert clean_marker["source_dirty"] is False
    assert clean_marker["source_tag"] is None
    assert clean_marker["source_tree_sha"]
    assert clean_marker["package_digest"]
    assert clean_marker["source_provenance_hash"]

    run(repo, "tag", "v4.9.0")
    assert source_tag(repo) == "v4.9.0"
    tagged_marker = build_package_marker(
        repo,
        package,
        package_name="ls-demo",
        package_type="skill",
        source_path=package,
        emitter="test",
        installed_at=False,
    )
    assert tagged_marker["source_tag"] == "v4.9.0"

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
    package = repo / "ls" / "skills" / "ls-demo"
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
        repo / "ls" / "docs" / "SKILLS.md",
        repo / "ls" / "docs" / "WORKFLOW_REGISTRY.md",
        repo / "ls" / "docs" / "_generated" / "facts.json",
        repo / "ls" / "docs" / "_generated" / "skill-taxonomy.json",
        repo / "ls" / "docs" / "migration" / "skill-alias-map.md",
        repo / "assets" / "README.md",
    ]
    for path in generated_files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("generated\n", encoding="utf-8")

    assert source_dirty(repo) is False

    (repo / "VERSION").write_text("3.9.1\n", encoding="utf-8")

    assert source_dirty(repo) is True


def test_repo_git_probes_ignore_inherited_scratch_index(tmp_path: Path, monkeypatch) -> None:
    repo = make_git_repo(tmp_path)
    package = repo / "ls" / "skills" / "ls-demo"
    expected_commit = run(repo, "rev-parse", "HEAD")
    expected_tree = run(repo, "rev-parse", "HEAD^{tree}")
    poison_index, alien = make_poison_index(tmp_path)

    raw_ls_files = subprocess.run(
        ["git", "ls-files", "--cached"],
        cwd=repo,
        env=clean_git_env(GIT_INDEX_FILE=str(poison_index)),
        text=True,
        capture_output=True,
        check=True,
    )
    assert ".agents/plugins/marketplace.json" in raw_ls_files.stdout

    monkeypatch.setenv("GIT_INDEX_FILE", str(poison_index))
    monkeypatch.setenv("GIT_DIR", str(alien / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(alien))

    marker = build_package_marker(
        repo,
        package,
        package_name="ls-demo",
        package_type="skill",
        source_path=package,
        emitter="test",
        installed_at=False,
    )

    assert marker["source_commit"] == expected_commit
    assert marker["source_tree_sha"] == expected_tree
    assert marker["source_dirty"] is False
    assert "VERSION" in tracked_files(repo)
    assert ".agents/plugins/marketplace.json" not in tracked_files(repo)


def test_source_remote_url_is_normalized_for_ci_parity(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path)

    run(repo, "remote", "add", "origin", "https://github.com/CruxExperts/localsetup.git")
    assert source_remote_url(repo) == "https://github.com/CruxExperts/localsetup"

    run(repo, "remote", "set-url", "origin", "git@github.com:CruxExperts/localsetup.git")
    assert source_remote_url(repo) == "https://github.com/CruxExperts/localsetup"


def test_generated_artifact_provenance_uses_parent_for_generated_commits(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path)
    generated = repo / "ls" / "docs" / "_generated" / "facts.json"
    generated.parent.mkdir(parents=True, exist_ok=True)
    parent = run(repo, "rev-parse", "HEAD")

    generated.write_text("{}\n", encoding="utf-8")
    run(repo, "add", str(generated.relative_to(repo)))
    run(repo, "commit", "-q", "-m", "docs: refresh generated artifacts")

    normal = base_provenance(repo, emitter="test")
    generated_mode = base_provenance(repo, emitter="test", generated_commit_parent=True)

    assert normal["source_commit"] == run(repo, "rev-parse", "HEAD")
    assert normal["source_dirty"] is False
    assert generated_mode["source_commit"] == parent
    assert generated_mode["source_dirty"] is False


def test_generated_artifact_provenance_walks_generated_commit_chain(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path)
    generated = repo / "ls" / "docs" / "_generated" / "facts.json"
    generated.parent.mkdir(parents=True, exist_ok=True)
    source = run(repo, "rev-parse", "HEAD")

    generated.write_text('{"step": 1}\n', encoding="utf-8")
    run(repo, "add", str(generated.relative_to(repo)))
    run(repo, "commit", "-q", "-m", "docs: refresh generated artifacts")

    generated.write_text('{"step": 2}\n', encoding="utf-8")
    run(repo, "add", str(generated.relative_to(repo)))
    run(repo, "commit", "-q", "-m", "docs: refresh generated provenance")

    generated_mode = base_provenance(repo, emitter="test", generated_commit_parent=True)

    assert generated_mode["source_commit"] == source
    assert generated_mode["source_dirty"] is False


def test_generated_artifact_provenance_uses_dirty_parent_for_release_sync(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path)
    parent = run(repo, "rev-parse", "HEAD")
    parent_tree = run(repo, "rev-parse", "HEAD^{tree}")

    (repo / "VERSION").write_text("3.9.1\n", encoding="utf-8")
    generated = repo / "ls" / "docs" / "SKILLS.md"
    generated.parent.mkdir(parents=True, exist_ok=True)
    generated.write_text("generated for release\n", encoding="utf-8")
    run(repo, "add", "VERSION", str(generated.relative_to(repo)))
    run(repo, "commit", "-q", "-m", "chore: sync release version 3.9.1")

    normal = base_provenance(repo, emitter="test")
    generated_mode = base_provenance(repo, emitter="test", generated_commit_parent=True)

    assert normal["source_commit"] == run(repo, "rev-parse", "HEAD")
    assert normal["source_dirty"] is False
    assert generated_mode["source_commit"] == parent
    assert generated_mode["source_tree_sha"] == parent_tree
    assert generated_mode["source_dirty"] is True


def test_generated_artifact_provenance_uses_release_sync_source_for_pr_merge_commit(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path)
    base = run(repo, "rev-parse", "HEAD")

    (repo / "ls" / "skills" / "ls-demo" / "SKILL.md").write_text(
        "---\nname: ls-demo\ndescription: Updated\n---\n",
        encoding="utf-8",
    )
    run(repo, "add", "ls/skills/ls-demo/SKILL.md")
    run(repo, "commit", "-q", "-m", "feat!: update runtime\n\nRelease-Type: major")
    source = run(repo, "rev-parse", "HEAD")
    source_tree = run(repo, "rev-parse", "HEAD^{tree}")

    (repo / "VERSION").write_text("4.0.0\n", encoding="utf-8")
    generated = repo / "ls" / "docs" / "_generated" / "facts.json"
    generated.parent.mkdir(parents=True, exist_ok=True)
    generated.write_text("{}\n", encoding="utf-8")
    run(repo, "add", "VERSION", str(generated.relative_to(repo)))
    run(repo, "commit", "-q", "-m", "chore: sync release version 4.0.0")
    release_sync = run(repo, "rev-parse", "HEAD")
    merge_tree = run(repo, "rev-parse", f"{release_sync}^{{tree}}")
    merge = run(
        repo,
        "commit-tree",
        merge_tree,
        "-p",
        base,
        "-p",
        release_sync,
        "-m",
        f"Merge {release_sync} into {base}",
    )
    run(repo, "reset", "--hard", merge)

    generated_mode = base_provenance(repo, emitter="test", generated_commit_parent=True)

    assert generated_mode["source_commit"] == source
    assert generated_mode["source_tree_sha"] == source_tree
    assert generated_mode["source_dirty"] is True


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
