"""
Purpose: Basic tests for Scrapling helper environment detection and wrappers.
Created: 2026-03-16
Last Updated: 2026-03-16
"""

from __future__ import annotations

from pathlib import Path

from _localsetup.tools.scrapling_helper import main as scrapling_main


def test_show_status_runs_without_error() -> None:
    text = scrapling_main.show_status()
    assert isinstance(text, str)
    assert "env_type" in text


def test_ensure_available_dry_run_does_not_apply() -> None:
    result = scrapling_main.ensure_available(dry_run=True, auto_confirm=False)
    assert result.applied is False
    # When pipx is missing, helpers may surface bootstrap plans; presence is optional here.
    assert hasattr(result, "pipx_bootstrap_plans")


def test_extract_url_simple_command_construction(tmp_path: Path, monkeypatch) -> None:
    called = {}

    def fake_apply(plan: list[str]) -> dict:
        # Record the most recent plan; return success by default.
        called.setdefault("plans", []).append(plan)
        return {"command": " ".join(plan), "returncode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(scrapling_main, "apply_command_plan", fake_apply)
    out = tmp_path / "out.md"
    result = scrapling_main.extract_url_simple("https://example.com", out, selector=None, mode_hint="get", use_docker=False)
    assert "scrapling extract get https://example.com" in result["command"]
    assert result["output_path"] == str(out)
    # With an explicit mode_hint we expect a single attempt using that mode.
    assert result["attempts"]
    assert len(result["attempts"]) == 1
    assert result["attempts"][0]["mode"] == "get"


def test_extract_url_simple_adaptive_escalates_on_failure(tmp_path: Path, monkeypatch) -> None:
    # Simulate a failing first attempt followed by a successful second attempt.
    calls: list[list[str]] = []

    def fake_apply(plan: list[str]) -> dict:
        calls.append(plan)
        # First call fails, second succeeds.
        if len(calls) == 1:
            return {"command": " ".join(plan), "returncode": 1, "stdout": "", "stderr": "network error"}
        return {"command": " ".join(plan), "returncode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(scrapling_main, "apply_command_plan", fake_apply)
    out = tmp_path / "out.md"
    result = scrapling_main.extract_url_simple("https://example.com", out, selector=None, mode_hint=None, use_docker=False)
    assert result["returncode"] == 0
    # Adaptive strategy should escalate from "get" to "fetch" on failure.
    assert result["mode"] == "fetch"
    assert len(result["attempts"]) == 2
    assert result["attempts"][0]["mode"] == "get"
    assert result["attempts"][1]["mode"] == "fetch"


def test_scrapling_self_test_offline_uses_file_fixture(tmp_path: Path, monkeypatch) -> None:
    # Force outputs_root to a temp directory so we do not touch real paths.
    cfg = scrapling_main.load_config()
    monkeypatch.setattr(cfg, "outputs_root", tmp_path)

    def fake_load_config():
        return cfg

    # Avoid real CLI calls by making extract_url_simple a no-op success.
    def fake_extract(url, output_path, selector=None, mode_hint=None, use_docker=False):
        return {
            "command": f"scrapling extract get {url} {output_path}",
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "mode": mode_hint or "get",
            "output_path": str(output_path),
            "attempts": [],
        }

    monkeypatch.setattr(scrapling_main, "load_config", fake_load_config)
    monkeypatch.setattr(scrapling_main, "extract_url_simple", fake_extract)

    summary = scrapling_main.scrapling_self_test(mode="offline")
    assert summary["self_test_mode"] == "offline"
    # Ensure a status_path is returned and the corresponding file exists.
    status_path = Path(summary["status_path"])
    assert status_path.exists()


def test_extract_url_structured_adaptive_respects_mode_hint(tmp_path: Path, monkeypatch) -> None:
    def fake_apply(plan: list[str]) -> dict:
        return {"command": " ".join(plan), "returncode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(scrapling_main, "apply_command_plan", fake_apply)
    out = tmp_path / "out.jsonl"
    schema = {"title": ".title"}
    result = scrapling_main.extract_url_structured(
        "https://example.com", out, selectors_schema=schema, mode_hint="dynamic", use_docker=False
    )
    assert result["mode"] == "dynamic"
    assert len(result["attempts"]) == 1
    assert result["attempts"][0]["mode"] == "dynamic"
