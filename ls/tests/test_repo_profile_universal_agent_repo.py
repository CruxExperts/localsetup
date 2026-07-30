import json
import subprocess
from pathlib import Path

import ls.core.cli as cli_mod


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_universal_agent_repo_profile_dry_run_writes_report_only(tmp_path: Path, capsys) -> None:
    root = _repo_root()
    target = tmp_path / "target"
    report = tmp_path / "report.json"

    code = cli_mod._main(
        [
            "--source-root",
            str(root),
            "wizard",
            "--repo-profile",
            "universal-agent-repo",
            "--target-directory",
            str(target),
            "--dry-run",
            "--report",
            str(report),
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    saved = json.loads(report.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["applied"] is False
    assert saved == payload
    assert not (target / "AGENTS.md").exists()
    assert any(action["relative_path"] == "AGENTS.md" and action["status"] == "create" for action in payload["actions"])


def test_universal_agent_repo_profile_apply_creates_shape_and_git_exclude(tmp_path: Path, capsys) -> None:
    root = _repo_root()
    target = tmp_path / "target"
    target.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=target, check=True)

    code = cli_mod._main(
        [
            "--source-root",
            str(root),
            "wizard",
            "--repo-profile",
            "universal-agent-repo",
            "--target-directory",
            str(target),
            "--apply",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["applied"] is True
    assert (target / "AGENTS.md").is_file()
    assert (target / "agent-repo-shape.json").is_file()
    assert (target / "external_skills.lock.json").is_file()
    assert (target / "docs" / "INDEX.md").is_file()
    assert (target / "docs" / "index.yaml").is_file()
    assert (target / "docs" / "reference" / "agent-repo-shape.md").is_file()
    assert subprocess.run(["git", "check-ignore", "-q", "--", ".agents/state/"], cwd=target, check=False).returncode == 0


def test_universal_agent_repo_profile_blocks_overwrite(tmp_path: Path, capsys) -> None:
    root = _repo_root()
    target = tmp_path / "target"
    target.mkdir()
    (target / "AGENTS.md").write_text("# Custom\n", encoding="utf-8")

    code = cli_mod._main(
        [
            "--source-root",
            str(root),
            "wizard",
            "--repo-profile",
            "universal-agent-repo",
            "--target-directory",
            str(target),
            "--apply",
        ]
    )

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["applied"] is False
    assert any("AGENTS.md" in blocker for blocker in payload["blockers"])
    assert (target / "AGENTS.md").read_text(encoding="utf-8") == "# Custom\n"
