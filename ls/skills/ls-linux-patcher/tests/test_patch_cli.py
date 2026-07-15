from __future__ import annotations

import json
import shlex
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


def _json_steps(result: subprocess.CompletedProcess[str]) -> list[dict[str, str]]:
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["steps"]


def _command_for_phase(steps: list[dict[str, str]], phase: str) -> str:
    for step in steps:
        if step["phase"] == phase:
            return step["command"]
    raise AssertionError(f"phase not found: {phase}")


def test_host_full_quotes_remote_path_with_spaces() -> None:
    result = run_cli("--json", "host-full", "admin@example.com", "/opt/docker apps")
    command = _command_for_phase(_json_steps(result), "docker-update")

    argv = shlex.split(command)

    assert argv[:2] == ["ssh", "admin@example.com"]
    assert argv[2] == "cd '/opt/docker apps' && sudo docker compose pull && sudo docker compose up -d"


def test_host_full_quotes_shell_metacharacters_in_remote_path() -> None:
    result = run_cli("--json", "host-full", "admin@example.com", "/opt/docker;rm -rf tmp")
    command = _command_for_phase(_json_steps(result), "docker-update")

    argv = shlex.split(command)

    assert argv[:2] == ["ssh", "admin@example.com"]
    assert argv[2] == "cd '/opt/docker;rm -rf tmp' && sudo docker compose pull && sudo docker compose up -d"


def test_multiple_quotes_remote_path_with_spaces(tmp_path: Path) -> None:
    config = tmp_path / "hosts.csv"
    config.write_text("admin@example.com,/srv/docker apps\n", encoding="utf-8")

    result = run_cli("--json", "multiple", str(config))
    command = _command_for_phase(_json_steps(result), "docker-verify")

    argv = shlex.split(command)

    assert argv[:2] == ["ssh", "admin@example.com"]
    assert argv[2] == "cd '/srv/docker apps' && sudo docker compose ps"
