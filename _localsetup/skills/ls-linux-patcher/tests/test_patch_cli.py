from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "patch_cli.py"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def test_status_reports_plan_only_and_unavailable_modes() -> None:
    result = run_cli("status")
    assert result.returncode == 0
    assert "Mode: plan-only" in result.stdout
    assert "PatchMon API querying" in result.stdout
    assert "remote SSH execution" in result.stdout


def test_status_json_is_machine_readable() -> None:
    result = run_cli("--json", "status")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["mode"] == "plan-only"
    assert "status" in payload["available"]
    assert "PatchMon API querying" in payload["unavailable"]


def test_auto_dry_run_is_guidance_only_without_missing_helper() -> None:
    result = run_cli("auto", "--dry-run")
    assert result.returncode == 0
    assert "guidance-only" in result.stdout
    assert "unavailable" in result.stdout
    assert "FileNotFoundError" not in result.stderr


def test_host_input_rejects_shell_operator() -> None:
    result = run_cli("host-only", "admin@example.com;rm")
    assert result.returncode == 2
    assert "InputError" in result.stderr
    assert "host:" in result.stderr
