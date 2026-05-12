import json
import shutil
import subprocess
import sys
from pathlib import Path

from _localsetup.v3.versioning import (
    SemVer,
    classify_commit,
    plan_version,
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


def next_minor_version(repo: Path) -> str:
    return str(repo_version(repo).bump("minor"))


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
    assert "version: 3.2" in (repo / "_localsetup/docs/migration/v2-to-v3-skill-map.md").read_text(encoding="utf-8")


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
        str(Path(__file__).resolve().parents[2] / "_localsetup" / "tools" / "localsetup_v3.py"),
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
        str(Path(__file__).resolve().parents[2] / "_localsetup" / "tools" / "localsetup_v3.py"),
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
    expected_version = next_minor_version(repo)

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
        "_localsetup/v3/adapters.py",
        "_localsetup/v3/apply.py",
        "_localsetup/config/install.schema.json",
        "_localsetup/templates/cursor/ls-context.mdc",
        "_localsetup/skills/ls-skill-creator/SKILL.md",
        "_localsetup/docs/MULTI_PLATFORM_INSTALL.md",
        "_localsetup/tests/test_v3_install_flow.py",
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
    expected_version = next_minor_version(repo)

    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    run(repo, "git", "add", "feature.txt")
    run(repo, "git", "commit", "-m", "feat: add release feature", "--no-verify")

    completed = run(
        repo,
        sys.executable,
        "_localsetup/tools/localsetup_v3.py",
        "release-push",
        "origin",
        "HEAD:main",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert run(repo, "git", "show", "origin/main:VERSION").stdout.strip() == expected_version
    assert run(repo, "git", "log", "-1", "--pretty=%s", "origin/main").stdout.strip() == f"chore: sync release version {expected_version}"
