from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "ls-linux-patcher" / "scripts" / "patch_cli.py"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, timeout=10)


def test_host_only_outputs_plan_without_executing_remote_command() -> None:
    result = run_cli("host-only", "admin@example.com")
    assert result.returncode == 0
    assert "Mode: plan-only" in result.stdout
    assert "ssh admin@example.com" in result.stdout


def test_rejects_shell_operator_in_host() -> None:
    result = run_cli("host-only", "admin@example.com;rm")
    assert result.returncode == 2
    assert "InputError" in result.stderr
    assert "host:" in result.stderr


def test_host_full_requires_absolute_docker_path() -> None:
    result = run_cli("host-full", "admin@example.com", "relative/path")
    assert result.returncode == 2
    assert "docker_path" in result.stderr
    assert "absolute path" in result.stderr


def test_multiple_config_accepts_simple_host_rows(tmp_path: Path) -> None:
    config = tmp_path / "hosts.conf"
    config.write_text("# comment\nadmin@example.com\nroot@example.net,/opt/docker\n", encoding="utf-8")
    result = run_cli("--json", "multiple", str(config))
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["mode"] == "plan-only"
    assert any("admin@example.com" in step["command"] for step in payload["steps"])
    assert any("/opt/docker" in step["command"] for step in payload["steps"])


def test_auto_mode_is_guidance_only() -> None:
    result = run_cli("auto", "--skip-docker")
    assert result.returncode == 0
    assert "guidance-only" in result.stdout
    assert "host-only" in result.stdout
