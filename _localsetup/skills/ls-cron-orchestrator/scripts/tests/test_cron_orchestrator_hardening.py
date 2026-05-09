import subprocess
import sys
from pathlib import Path

import yaml


SCRIPT_DIR = Path(__file__).resolve().parents[1]
ROOT = SCRIPT_DIR.parents[3]
CRON_CTL = SCRIPT_DIR / "cron_ctl.py"


def _write_manifest(path: Path, payload: dict) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _run_cron_ctl(manifest: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CRON_CTL), "--manifest", str(manifest), *args],
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )


def test_validate_rejects_unsafe_schedule_characters(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.yaml"
    _write_manifest(
        manifest,
        {
            "triggers": {"bad": {"schedule": "0 0 * * *%/bin/sh"}},
            "tasks": [{"id": "safe", "trigger": "bad", "sequence_order": 1, "command": ["python3", "--version"]}],
        },
    )

    proc = _run_cron_ctl(manifest, "validate")

    assert proc.returncode == 1
    assert "triggers.bad.schedule" in proc.stderr
    assert "unsupported cron characters" in proc.stderr


def test_validate_allows_literal_shell_looking_argv_args(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.yaml"
    _write_manifest(
        manifest,
        {
            "triggers": {"nightly": {"schedule": "0 2 * * *"}},
            "tasks": [{"id": "literal", "trigger": "nightly", "sequence_order": 1, "command": ["printf", "a && b"]}],
        },
    )

    proc = _run_cron_ctl(manifest, "validate")

    assert proc.returncode == 0
    assert proc.stdout.strip() == "OK"


def test_install_quotes_runner_args_without_shell_chaining(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo root %safe"
    repo_root.mkdir()
    manifest = tmp_path / "manifest.yaml"
    _write_manifest(
        manifest,
        {
            "triggers": {
                "nightly": {"schedule": "0 2 * * *"},
                "after-boot": {"on_boot_delay_minutes": 5},
            },
            "tasks": [
                {"id": "night-task", "trigger": "nightly", "sequence_order": 1, "command": ["python3", "--version"]},
                {"id": "boot-task", "trigger": "after-boot", "sequence_order": 1, "command": ["python3", "--version"]},
            ],
        },
    )

    proc = _run_cron_ctl(manifest, "install", "--repo-root", str(repo_root))

    expected_repo_root = str(repo_root).replace("%", r"\%")
    assert proc.returncode == 0
    assert f"--repo-root '{expected_repo_root}'" in proc.stdout
    assert "--delay-seconds 300" in proc.stdout
    assert " && " not in proc.stdout
    assert "\tcd " not in proc.stdout
    assert "\tsleep " not in proc.stdout
