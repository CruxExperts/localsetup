from __future__ import annotations

import subprocess
from pathlib import Path

from _localsetup.v3.repo_finalizer import plan as finalizer_plan
from _localsetup.v3.repo_finalizer import run as finalizer_run
from _localsetup.v3.repo_finalizer import status as finalizer_status


ROOT = Path(__file__).resolve().parents[2]


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "tests@example.com")
    _git(repo, "config", "user.name", "Tests")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "--", "README.md")
    _git(repo, "commit", "-m", "seed")
    return repo


def _class_for(payload: dict, path: str) -> str:
    match = next(row for row in payload["files"] if row["path"] == path)
    return str(match["classification"])


def test_clean_repo(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    payload = finalizer_plan(ROOT, repo)
    assert payload["ok"] is True
    assert payload["status"] == "clean"
    assert payload["summary"]["total_dirty_files"] == 0


def test_allowlisted_managed_output_stages(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    target = repo / "_localsetup" / "docs" / "_generated"
    target.mkdir(parents=True)
    file_path = target / "facts.json"
    file_path.write_text("{}\n", encoding="utf-8")

    payload = finalizer_run(ROOT, repo)

    assert payload["ok"] is True
    assert _class_for(payload, "_localsetup/docs/_generated/facts.json") == "generated_artifact"
    staged = _git(repo, "diff", "--cached", "--name-only")
    assert "_localsetup/docs/_generated/facts.json" in staged.stdout


def test_default_policy_stages_lock_and_heartbeat_outputs(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    (repo / "localsetup.lock.json").write_text("{}\n", encoding="utf-8")
    config = repo / "config"
    config.mkdir()
    (config / "localsetup_finalizer.yaml").write_text("{}\n", encoding="utf-8")
    (config / "codex_heartbeat.yaml").write_text("heartbeat:\n  enabled: false\n", encoding="utf-8")
    cron = repo / "cron"
    cron.mkdir()
    (cron / "manifest.yaml").write_text("triggers: {}\ntasks: []\n", encoding="utf-8")

    payload = finalizer_run(ROOT, repo)

    assert payload["ok"] is True
    assert _class_for(payload, "localsetup.lock.json") == "managed_output"
    assert _class_for(payload, "config/localsetup_finalizer.yaml") == "managed_output"
    assert _class_for(payload, "config/codex_heartbeat.yaml") == "managed_output"
    assert _class_for(payload, "cron/manifest.yaml") == "managed_output"
    staged = _git(repo, "diff", "--cached", "--name-only")
    assert set(staged.stdout.splitlines()) == {
        "config/codex_heartbeat.yaml",
        "config/localsetup_finalizer.yaml",
        "cron/manifest.yaml",
        "localsetup.lock.json",
    }


def test_unknown_modified_block(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    managed = repo / "_localsetup" / "config"
    managed.mkdir(parents=True)
    tracked = managed / "generated.txt"
    tracked.write_text("v1\n", encoding="utf-8")
    _git(repo, "add", "--", str(tracked.relative_to(repo)))
    _git(repo, "commit", "-m", "add managed")
    tracked.write_text("v2\n", encoding="utf-8")

    payload = finalizer_run(ROOT, repo)

    assert payload["ok"] is False
    assert _class_for(payload, "_localsetup/config/generated.txt") == "unknown_change"


def test_user_owned_dirty_block(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    notes = repo / "notes.md"
    notes.write_text("hi\n", encoding="utf-8")
    _git(repo, "add", "--", "notes.md")
    _git(repo, "commit", "-m", "notes")
    notes.write_text("edited\n", encoding="utf-8")

    payload = finalizer_status(ROOT, repo)

    assert payload["summary"]["blockers"] == 1
    assert _class_for(payload, "notes.md") == "user_change"


def test_unknown_untracked_block(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    (repo / "scratch.txt").write_text("x\n", encoding="utf-8")
    (repo / "Cargo.lock").write_text("user lockfile\n", encoding="utf-8")

    payload = finalizer_plan(ROOT, repo)

    assert _class_for(payload, "scratch.txt") == "unknown_change"
    assert _class_for(payload, "Cargo.lock") == "unknown_change"
    assert payload["summary"]["blockers"] == 2


def test_git_ignored_runtime_state(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    (repo / ".gitignore").write_text("state/\n", encoding="utf-8")
    _git(repo, "add", "--", ".gitignore")
    _git(repo, "commit", "-m", "ignore state")
    runtime = repo / "state" / "repo-finalizer"
    runtime.mkdir(parents=True)
    (runtime / "report.json").write_text("{}\n", encoding="utf-8")

    payload = finalizer_plan(ROOT, repo)

    assert _class_for(payload, "state/repo-finalizer/report.json") == "runtime_ignored"
    assert payload["summary"]["blockers"] == 0
    assert payload["status"] == "clean_except_ignored"


def test_existing_non_ignored_runtime_state_blocks(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    runtime = repo / "state" / "repo-finalizer"
    runtime.mkdir(parents=True)
    (runtime / "latest.json").write_text("{}\n", encoding="utf-8")

    payload = finalizer_plan(ROOT, repo)

    assert _class_for(payload, "state/repo-finalizer/latest.json") == "unknown_change"
    assert payload["summary"]["blockers"] == 1
    assert payload["status"] == "blocked"


def test_run_reports_are_locally_excluded(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)

    payload = finalizer_run(ROOT, repo, no_commit=True)

    assert payload["ok"] is True
    assert _git(repo, "check-ignore", "-q", "--", "state/repo-finalizer/latest.json").returncode == 0
    status = finalizer_status(ROOT, repo)
    assert status["status"] == "clean_except_ignored"
    assert all(row["classification"] == "runtime_ignored" for row in status["files"])


def test_read_only_plan(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    target = repo / "_localsetup" / "docs" / "_generated"
    target.mkdir(parents=True)
    (target / "facts.json").write_text("{}\n", encoding="utf-8")

    _ = finalizer_plan(ROOT, repo)

    staged = _git(repo, "diff", "--cached", "--name-only")
    assert staged.stdout.strip() == ""


def test_run_no_commit_never_stages(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    target = repo / "_localsetup" / "docs" / "_generated"
    target.mkdir(parents=True)
    (target / "facts.json").write_text("{}\n", encoding="utf-8")

    payload = finalizer_run(ROOT, repo, no_commit=True)

    assert payload["ok"] is True
    assert "report_paths" in payload
    assert (repo / "state" / "repo-finalizer" / "latest.json").is_file()
    assert (repo / "state" / "repo-finalizer" / "latest.md").is_file()
    staged = _git(repo, "diff", "--cached", "--name-only")
    assert staged.stdout.strip() == ""


def test_checkpoint_commit_only_allowlisted_files(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    managed = repo / "_localsetup" / "docs" / "_generated"
    managed.mkdir(parents=True)
    (managed / "facts.json").write_text("{}\n", encoding="utf-8")

    payload = finalizer_run(ROOT, repo, checkpoint=True, message="checkpoint managed outputs")

    assert payload["ok"] is True
    last = _git(repo, "show", "--name-only", "--pretty=format:", "HEAD")
    changed = [line.strip() for line in last.stdout.splitlines() if line.strip()]
    assert changed == ["_localsetup/docs/_generated/facts.json"]


def test_deleted_allowlisted_file_blocks(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    managed = repo / "_localsetup" / "docs" / "_generated"
    managed.mkdir(parents=True)
    facts = managed / "facts.json"
    facts.write_text("{}\n", encoding="utf-8")
    _git(repo, "add", "--", "_localsetup/docs/_generated/facts.json")
    _git(repo, "commit", "-m", "add generated facts")
    facts.unlink()

    payload = finalizer_run(ROOT, repo)

    assert payload["ok"] is False
    row = next(row for row in payload["files"] if row["path"] == "_localsetup/docs/_generated/facts.json")
    assert row["deleted"] is True
    assert row["blocker"] is True
    staged = _git(repo, "diff", "--cached", "--name-only")
    assert staged.stdout.strip() == ""


def test_renamed_file_into_allowlist_blocks(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    source = repo / "notes.md"
    source.write_text("note\n", encoding="utf-8")
    _git(repo, "add", "--", "notes.md")
    _git(repo, "commit", "-m", "add notes")
    generated = repo / "_localsetup" / "docs" / "_generated"
    generated.mkdir(parents=True)
    source.rename(generated / "facts.json")
    _git(repo, "add", "--", "notes.md", "_localsetup/docs/_generated/facts.json")

    payload = finalizer_run(ROOT, repo)

    assert payload["ok"] is False
    row = next(row for row in payload["files"] if row["path"] == "_localsetup/docs/_generated/facts.json")
    assert row["renamed_or_copied"] is True
    assert row["blocker"] is True
    staged = _git(repo, "diff", "--cached", "--name-status")
    assert "R" in staged.stdout


def test_mixed_managed_and_unknown_blocks(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    managed = repo / "_localsetup" / "docs" / "_generated"
    managed.mkdir(parents=True)
    (managed / "facts.json").write_text("{}\n", encoding="utf-8")
    (repo / "local.tmp").write_text("x\n", encoding="utf-8")

    payload = finalizer_run(ROOT, repo)

    assert payload["ok"] is False
    assert payload["summary"]["blockers"] == 1
    staged = _git(repo, "diff", "--cached", "--name-only")
    assert staged.stdout.strip() == ""


def test_non_git_target_reports_unsupported(tmp_path: Path) -> None:
    target = tmp_path / "not-git"
    target.mkdir()
    payload = finalizer_plan(ROOT, target)
    assert payload["ok"] is False
    assert payload["status"] == "unsupported"


def test_no_push_surface_in_actions(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    target = repo / "_localsetup" / "docs" / "_generated"
    target.mkdir(parents=True)
    (target / "facts.json").write_text("{}\n", encoding="utf-8")

    payload = finalizer_run(ROOT, repo, checkpoint=True, message="checkpoint")

    action_json = str(payload.get("actions", []))
    assert "push" not in action_json
