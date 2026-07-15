import json
import subprocess
import sys
from pathlib import Path

from ls.core.versioning import SemVer, publish_preflight
from ls.tests.versioning_test_helpers import (
    copy_full_repo,
    init_git_repo,
    next_patch_version,
    repo_version,
    run,
)


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
        "ls/tools/localsetup.py",
        "release-push",
        "origin",
        "HEAD:main",
        check=False,
    )

    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["release_type_required"] is True
    assert run(repo, "git", "log", "-1", "--pretty=%s").stdout.strip() == "feat!: replace API"
    assert run(repo, "git", "rev-parse", "origin/main").stdout.strip() == run(
        repo, "git", "rev-parse", "HEAD~1"
    ).stdout.strip()
    assert repo_version(repo) == original_version
    assert run(repo, "git", "status", "--short").stdout.strip() == ""


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
        "ls/tools/localsetup.py",
        "release-push",
        "origin",
        "HEAD:main",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert run(repo, "git", "show", "origin/main:VERSION").stdout.strip() == expected_version
    assert (
        run(repo, "git", "log", "-1", "--pretty=%s", "origin/main").stdout.strip()
        == f"chore: sync release version {expected_version}"
    )
