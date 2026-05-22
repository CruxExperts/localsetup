import json
import shutil
import subprocess
import sys
from pathlib import Path

from _localsetup.core.versioning import (
    SemVer,
    classify_commit,
    plan_version,
    publish_preflight,
    sync_version_files,
)


def copy_full_repo(tmp_path: Path) -> Path:
    source = Path(__file__).resolve().parents[2]
    repo = tmp_path / "repo"
    shutil.copytree(
        source,
        repo,
        ignore=shutil.ignore_patterns(
            ".git",
            ".venv",
            ".venv-*",
            "__pycache__",
            ".pytest_cache",
            "localsetup.egg-info",
            "logs",
            "scrapling_output",
        ),
    )
    return repo


def run(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=repo,
        text=True,
        capture_output=True,
        check=check,
    )


def init_git_repo(repo: Path, remote: Path) -> None:
    run(repo, "git", "init", "-q")
    run(repo, "git", "config", "user.email", "test@example.com")
    run(repo, "git", "config", "user.name", "Test User")
    run(repo, "git", "add", ".")
    run(repo, "git", "commit", "-m", "chore: initial", "--no-verify")
    run(repo, "git", "branch", "-M", "main")
    run(repo, "git", "remote", "add", "origin", str(remote))
    run(repo, "git", "push", "-u", "origin", "main", "--no-verify")


def repo_version(repo: Path) -> SemVer:
    return SemVer.parse((repo / "VERSION").read_text(encoding="utf-8").strip())


def next_patch_version(repo: Path) -> str:
    return str(repo_version(repo).bump("patch"))


def test_semver_and_commit_classification() -> None:
    assert str(SemVer.parse("3.0.0").bump("major")) == "4.0.0"
    assert str(SemVer.parse("3.0.0").bump("minor")) == "3.1.0"
    assert str(SemVer.parse("3.0.0").bump("patch")) == "3.0.1"
    assert classify_commit("feat: add hook") == "minor"
    assert classify_commit("fix(parser): handle edge") == "patch"
    assert classify_commit("revert: remove change") == "patch"
    assert classify_commit("feat!: replace API") == "major"
    assert classify_commit("chore: internal", "BREAKING CHANGE: config format") == "major"
    assert classify_commit("feat: internal", "Release-Type: patch") == "patch"
    assert classify_commit("feat: internal", "Release-Type: minor") == "minor"
    assert classify_commit("Merge branch 'x'") == "none"
    assert classify_commit("chore: sync release version 3.1.0") == "none"


def test_release_plan_patch_default_for_routine_feat(tmp_path: Path) -> None:
    repo = copy_full_repo(tmp_path)
    remote = tmp_path / "remote.git"
    run(tmp_path, "git", "init", "--bare", str(remote))
    init_git_repo(repo, remote)

    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    run(repo, "git", "add", "feature.txt")
    run(repo, "git", "commit", "-m", "feat: add routine capability", "--no-verify")

    plan = plan_version(repo, base="origin/main", head="HEAD")
    expected = repo_version(repo).bump("patch")

    assert plan["policy"] == "patch-default"
    assert plan["commits"][0]["raw_bump"] == "minor"
    assert plan["commits"][0]["bump"] == "patch"
    assert plan["bump"] == "patch"
    assert plan["target_version"] == str(expected)


def test_release_plan_batches_multiple_normal_commits_as_one_patch(tmp_path: Path) -> None:
    repo = copy_full_repo(tmp_path)
    remote = tmp_path / "remote.git"
    run(tmp_path, "git", "init", "--bare", str(remote))
    init_git_repo(repo, remote)

    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    run(repo, "git", "add", "feature.txt")
    run(repo, "git", "commit", "-m", "feat: add routine capability", "--no-verify")
    (repo / "fix.txt").write_text("fix\n", encoding="utf-8")
    run(repo, "git", "add", "fix.txt")
    run(repo, "git", "commit", "-m", "fix: polish routine capability", "--no-verify")

    plan = plan_version(repo, base="origin/main", head="HEAD")
    expected = repo_version(repo).bump("patch")

    assert plan["bump"] == "patch"
    assert plan["target_version"] == str(expected)
    assert plan["commit_count"] == 2
    assert plan["net_commit_count"] == 2


def test_publish_preflight_fix_creates_release_and_generated_docs_commits(tmp_path: Path) -> None:
    repo = copy_full_repo(tmp_path)
    remote = tmp_path / "remote.git"
    run(tmp_path, "git", "init", "--bare", str(remote))
    init_git_repo(repo, remote)
    expected = str(repo_version(repo).bump("patch"))

    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    run(repo, "git", "add", "feature.txt")
    run(repo, "git", "commit", "-m", "feat: add routine capability", "--no-verify")

    result = publish_preflight(repo, base="origin/main", head="HEAD", fix=True)

    assert result["ok"] is True
    assert result["fixed"] is True
    assert [commit["type"] for commit in result["commits"]] in (
        ["version_sync"],
        ["version_sync", "generated_docs"],
    )
    subjects = run(repo, "git", "log", "--format=%s", "-2").stdout.splitlines()
    assert f"chore: sync release version {expected}" in subjects
    assert repo_version(repo) == SemVer.parse(expected)
    assert run(repo, "git", "status", "--short").stdout.strip() == ""


def test_publish_preflight_fix_requires_clean_worktree(tmp_path: Path) -> None:
    repo = copy_full_repo(tmp_path)
    remote = tmp_path / "remote.git"
    run(tmp_path, "git", "init", "--bare", str(remote))
    init_git_repo(repo, remote)

    (repo / "scratch.txt").write_text("scratch\n", encoding="utf-8")

    result = publish_preflight(repo, base="origin/main", head="HEAD", fix=True)

    assert result["ok"] is False
    assert result["reason"] == "dirty_worktree"
    assert "scratch.txt" in result["dirty_worktree"]
    assert run(repo, "git", "log", "-1", "--pretty=%s").stdout.strip() == "chore: initial"


def test_release_type_trailers_control_effective_bump(tmp_path: Path) -> None:
    cases = [
        ("Release-Type: minor", "minor"),
        ("Release-Type: major", "major"),
        ("Release-Type: patch", "patch"),
        ("Release-Type: none", "none"),
    ]
    for trailer, bump in cases:
        case_root = tmp_path / bump
        case_root.mkdir()
        repo = copy_full_repo(case_root)
        remote = tmp_path / f"{bump}.git"
        run(tmp_path, "git", "init", "--bare", str(remote))
        init_git_repo(repo, remote)

        (repo / f"{bump}.txt").write_text(f"{bump}\n", encoding="utf-8")
        run(repo, "git", "add", f"{bump}.txt")
        run(repo, "git", "commit", "-m", "feat: add explicit release", "-m", trailer, "--no-verify")

        plan = plan_version(repo, base="origin/main", head="HEAD")

        assert plan["bump"] == bump
        assert plan["release_type_required"] is False
        assert plan["target_version"] == str(repo_version(repo).bump(bump))


def test_breaking_markers_require_release_type_trailer(tmp_path: Path) -> None:
    cases = [
        ("feat!: replace API", ""),
        ("feat: replace API", "BREAKING CHANGE: config format"),
    ]
    for index, (subject, body) in enumerate(cases):
        case_root = tmp_path / f"breaking-{index}"
        case_root.mkdir()
        repo = copy_full_repo(case_root)
        remote = tmp_path / f"breaking-{index}.git"
        run(tmp_path, "git", "init", "--bare", str(remote))
        init_git_repo(repo, remote)

        (repo / "breaking.txt").write_text(f"breaking {index}\n", encoding="utf-8")
        run(repo, "git", "add", "breaking.txt")
        commit_args = ["git", "commit", "-m", subject]
        if body:
            commit_args.extend(["-m", body])
        commit_args.append("--no-verify")
        run(repo, *commit_args)

        plan = plan_version(repo, base="origin/main", head="HEAD")

        assert plan["ok"] is False
        assert plan["release_type_required"] is True
        assert plan["release_type_required_commits"][0]["subject"] == subject
        assert plan["commits"][0]["raw_bump"] == "major"
        assert plan["commits"][0]["bump"] == "patch"


def test_version_plan_cli_fails_for_breaking_marker_without_release_type(tmp_path: Path) -> None:
    repo = copy_full_repo(tmp_path)
    remote = tmp_path / "remote.git"
    run(tmp_path, "git", "init", "--bare", str(remote))
    init_git_repo(repo, remote)

    (repo / "breaking.txt").write_text("breaking\n", encoding="utf-8")
    run(repo, "git", "add", "breaking.txt")
    run(repo, "git", "commit", "-m", "feat!: replace API", "--no-verify")

    completed = run(
        repo,
        sys.executable,
        "_localsetup/tools/localsetup.py",
        "version-plan",
        "--base",
        "origin/main",
        "--head",
        "HEAD",
        check=False,
    )

    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["ok"] is False
    assert payload["release_type_required"] is True
    assert "Release-Type: major|minor|patch|none" in payload["release_type_required_commits"][0]["message"]


def test_pre_push_hook_blocks_breaking_marker_without_sync_commit(tmp_path: Path) -> None:
    repo = copy_full_repo(tmp_path)
    remote = tmp_path / "remote.git"
    run(tmp_path, "git", "init", "--bare", str(remote))
    init_git_repo(repo, remote)
    original_version = repo_version(repo)

    (repo / "breaking.txt").write_text("breaking\n", encoding="utf-8")
    run(repo, "git", "add", "breaking.txt")
    run(repo, "git", "commit", "-m", "feat!: replace API", "--no-verify")
    local_sha = run(repo, "git", "rev-parse", "HEAD").stdout.strip()
    remote_sha = run(repo, "git", "rev-parse", "origin/main").stdout.strip()

    completed = subprocess.run(
        [str(repo / ".githooks/pre-push"), "origin", str(remote)],
        cwd=repo,
        input=f"refs/heads/main {local_sha} refs/heads/main {remote_sha}\n",
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "requires Release-Type: major|minor|patch|none" in completed.stderr
    assert run(repo, "git", "log", "-1", "--pretty=%s").stdout.strip() == "feat!: replace API"
    assert repo_version(repo) == original_version
    assert run(repo, "git", "status", "--short").stdout.strip() == ""


def test_release_push_blocks_breaking_marker_without_sync_commit(tmp_path: Path) -> None:
    repo = copy_full_repo(tmp_path)
    remote = tmp_path / "remote.git"
    run(tmp_path, "git", "init", "--bare", str(remote))
    init_git_repo(repo, remote)
    original_version = repo_version(repo)

    (repo / "breaking.txt").write_text("breaking\n", encoding="utf-8")
    run(repo, "git", "add", "breaking.txt")
    run(repo, "git", "commit", "-m", "feat!: replace API", "--no-verify")

    completed = run(
        repo,
        sys.executable,
        "_localsetup/tools/localsetup.py",
        "release-push",
        "origin",
        "HEAD:main",
        check=False,
    )

    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["release_type_required"] is True
    assert run(repo, "git", "log", "-1", "--pretty=%s").stdout.strip() == "feat!: replace API"
    assert run(repo, "git", "rev-parse", "origin/main").stdout.strip() == run(repo, "git", "rev-parse", "HEAD~1").stdout.strip()
    assert repo_version(repo) == original_version
    assert run(repo, "git", "status", "--short").stdout.strip() == ""


def test_sync_version_files_updates_known_surfaces(tmp_path: Path) -> None:
    repo = copy_full_repo(tmp_path)

    sync_version_files(repo, "3.2.0")

    assert (repo / "VERSION").read_text(encoding="utf-8").strip() == "3.2.0"
    assert 'version = "3.2.0"' in (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert "**Version:** 3.2.0<br>" in (repo / "README.md").read_text(encoding="utf-8")
    assert "**Version:** 3.2.0<br>" in (repo / "_localsetup/README.md").read_text(encoding="utf-8")
    assert "- Current value: `3.2.0`" in (repo / "_localsetup/docs/VERSIONING.md").read_text(encoding="utf-8")
    assert "version: 3.2" in (repo / "_localsetup/docs/README.md").read_text(encoding="utf-8")
    assert '"version": "3.2.0"' in (repo / "_localsetup/docs/_generated/facts.json").read_text(encoding="utf-8")
    assert '"version": "3.2.0"' in (repo / "_localsetup/docs/_generated/docs-truth-map.json").read_text(encoding="utf-8")
    assert "| Version | `3.2.0` |" in (repo / "_localsetup/docs/_generated/docs-alignment-summary.md").read_text(encoding="utf-8")
    assert '"count":' in (repo / "_localsetup/docs/_generated/workflow-catalog.json").read_text(encoding="utf-8")
    assert "version: 3.2" in (repo / "_localsetup/docs/WORKFLOW_REGISTRY.md").read_text(encoding="utf-8")
    assert "version: 3.2" in (repo / "_localsetup/docs/migration/skill-alias-map.md").read_text(encoding="utf-8")


def test_revert_before_push_cancels_unreleased_bump(tmp_path: Path) -> None:
    repo = copy_full_repo(tmp_path)
    remote = tmp_path / "remote.git"
    run(tmp_path, "git", "init", "--bare", str(remote))
    init_git_repo(repo, remote)

    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    run(repo, "git", "add", "feature.txt")
    run(repo, "git", "commit", "-m", "feat: add temporary feature", "--no-verify")
    run(repo, "git", "revert", "--no-edit", "HEAD")

    plan = plan_version(repo, base="origin/main", head="HEAD")

    assert plan["bump"] == "none"
    assert plan["target_version"] == str(repo_version(repo))
    assert plan["canceled_reverts"]


def test_version_plan_uses_release_sync_commit_version_as_target(tmp_path: Path) -> None:
    repo = copy_full_repo(tmp_path)
    remote = tmp_path / "remote.git"
    run(tmp_path, "git", "init", "--bare", str(remote))
    init_git_repo(repo, remote)
    expected = str(repo_version(repo).bump("patch"))

    (repo / "bugfix.txt").write_text("bugfix\n", encoding="utf-8")
    run(repo, "git", "add", "bugfix.txt")
    run(repo, "git", "commit", "-m", "fix: resolve release bug", "--no-verify")
    sync_version_files(repo, expected)
    run(repo, "git", "add", ".")
    run(repo, "git", "commit", "-m", f"chore: sync release version {expected}", "--no-verify")

    plan = plan_version(repo, base="origin/main", head="HEAD")

    assert plan["ok"] is True
    assert plan["version_sync_present"] is True
    assert plan["target_version"] == expected
    assert plan["current_version"] == expected


def test_version_plan_uses_local_main_when_no_remote_exists(tmp_path: Path) -> None:
    repo = tmp_path / "consumer"
    repo.mkdir()
    (repo / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    run(repo, "git", "init", "-q", "-b", "main")
    run(repo, "git", "config", "user.email", "test@example.invalid")
    run(repo, "git", "config", "user.name", "Test User")
    run(repo, "git", "add", "VERSION")
    run(repo, "git", "commit", "-q", "-m", "chore: initial")

    completed = run(
        repo,
        sys.executable,
        str(Path(__file__).resolve().parents[2] / "_localsetup" / "tools" / "localsetup.py"),
        "--repo",
        str(repo),
        "version-plan",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert payload["commit_count"] == 0
    assert payload["base_resolution"]["status"] == "resolved"
    assert payload["base_resolution"]["strategy"] == "local_main"
    assert payload["base_resolution"]["ref"] == "main"


def test_version_plan_reports_no_comparison_base_for_detached_repo_without_named_base(tmp_path: Path) -> None:
    repo = tmp_path / "detached"
    repo.mkdir()
    (repo / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    run(repo, "git", "init", "-q")
    run(repo, "git", "config", "user.email", "test@example.invalid")
    run(repo, "git", "config", "user.name", "Test User")
    run(repo, "git", "add", "VERSION")
    run(repo, "git", "commit", "-q", "-m", "chore: initial")
    head = run(repo, "git", "rev-parse", "HEAD").stdout.strip()
    run(repo, "git", "checkout", "--detach", head)
    run(repo, "git", "branch", "-D", "master")

    plan = plan_version(repo)

    assert plan["ok"] is True
    assert plan["commit_count"] == 0
    assert plan["base"] == plan["head"]
    assert plan["base_resolution"]["status"] == "no_comparison_base"


def test_version_plan_invalid_explicit_base_fails_instead_of_falling_back(tmp_path: Path) -> None:
    repo = tmp_path / "consumer"
    repo.mkdir()
    (repo / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    run(repo, "git", "init", "-q", "-b", "main")
    run(repo, "git", "config", "user.email", "test@example.invalid")
    run(repo, "git", "config", "user.name", "Test User")
    run(repo, "git", "add", "VERSION")
    run(repo, "git", "commit", "-q", "-m", "chore: initial")

    completed = run(
        repo,
        sys.executable,
        str(Path(__file__).resolve().parents[2] / "_localsetup" / "tools" / "localsetup.py"),
        "--repo",
        str(repo),
        "version-plan",
        "--base",
        "definitely-missing-ref",
        check=False,
    )

    assert completed.returncode == 2
    assert "explicit base ref did not resolve: definitely-missing-ref" in completed.stderr


def test_pre_push_hook_creates_sync_commit_and_blocks_stale_push(tmp_path: Path) -> None:
    repo = copy_full_repo(tmp_path)
    remote = tmp_path / "remote.git"
    run(tmp_path, "git", "init", "--bare", str(remote))
    init_git_repo(repo, remote)
    expected_version = next_patch_version(repo)

    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    run(repo, "git", "add", "feature.txt")
    run(repo, "git", "commit", "-m", "feat: add prepush feature", "--no-verify")
    local_sha = run(repo, "git", "rev-parse", "HEAD").stdout.strip()
    remote_sha = run(repo, "git", "rev-parse", "origin/main").stdout.strip()

    completed = subprocess.run(
        [str(repo / ".githooks/pre-push"), "origin", str(remote)],
        cwd=repo,
        input=f"refs/heads/main {local_sha} refs/heads/main {remote_sha}\n",
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "push stopped" in completed.stderr
    assert run(repo, "git", "log", "-1", "--pretty=%s").stdout.strip() == f"chore: sync release version {expected_version}"
    assert (repo / "VERSION").read_text(encoding="utf-8").strip() == expected_version
    assert run(repo, "git", "status", "--short").stdout.strip() == ""


def test_internal_release_tooling_feat_is_patch(tmp_path: Path) -> None:
    repo = copy_full_repo(tmp_path)
    remote = tmp_path / "remote.git"
    run(tmp_path, "git", "init", "--bare", str(remote))
    init_git_repo(repo, remote)

    docs = repo / "_localsetup" / "docs" / "VERSIONING.md"
    docs.write_text(docs.read_text(encoding="utf-8") + "\nRelease note.\n", encoding="utf-8")
    run(repo, "git", "add", str(docs.relative_to(repo)))
    run(repo, "git", "commit", "-m", "feat: automate release docs", "--no-verify")

    plan = plan_version(repo, base="origin/main", head="HEAD")
    expected = repo_version(repo).bump("patch")

    assert plan["bump"] == "patch"
    assert plan["target_version"] == str(expected)
    assert plan["commits"][0]["raw_bump"] == "minor"


def test_installer_adapter_maintenance_feat_is_patch(tmp_path: Path) -> None:
    repo = copy_full_repo(tmp_path)
    remote = tmp_path / "remote.git"
    run(tmp_path, "git", "init", "--bare", str(remote))
    init_git_repo(repo, remote)

    touched = [
        ".gitignore",
        "install",
        "_localsetup/core/adapters.py",
        "_localsetup/core/apply.py",
        "_localsetup/config/install.schema.json",
        "_localsetup/templates/cursor/ls-context.mdc",
        "_localsetup/skills/ls-skill-creator/SKILL.md",
        "_localsetup/docs/MULTI_PLATFORM_INSTALL.md",
        "_localsetup/tests/test_install_flow.py",
    ]
    for rel_path in touched:
        path = repo / rel_path
        path.write_text(path.read_text(encoding="utf-8") + "\n# release classification fixture\n", encoding="utf-8")
    run(repo, "git", "add", *touched)
    run(repo, "git", "commit", "-m", "feat: require explicit adapter attachment", "--no-verify")

    plan = plan_version(repo, base="origin/main", head="HEAD")
    expected = repo_version(repo).bump("patch")

    assert plan["commits"][0]["raw_bump"] == "minor"
    assert plan["bump"] == "patch"
    assert plan["target_version"] == str(expected)


def test_release_push_commits_sync_and_pushes(tmp_path: Path) -> None:
    repo = copy_full_repo(tmp_path)
    remote = tmp_path / "remote.git"
    run(tmp_path, "git", "init", "--bare", str(remote))
    init_git_repo(repo, remote)
    expected_version = next_patch_version(repo)

    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    run(repo, "git", "add", "feature.txt")
    run(repo, "git", "commit", "-m", "feat: add release feature", "--no-verify")

    completed = run(
        repo,
        sys.executable,
        "_localsetup/tools/localsetup.py",
        "release-push",
        "origin",
        "HEAD:main",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert run(repo, "git", "show", "origin/main:VERSION").stdout.strip() == expected_version
    assert run(repo, "git", "log", "-1", "--pretty=%s", "origin/main").stdout.strip() == f"chore: sync release version {expected_version}"
