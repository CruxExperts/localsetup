"""
Purpose: Tests for Scrapling adapter parser and refresh flow.
Created: 2026-03-16
Last Updated: 2026-03-16
"""

from __future__ import annotations

import json
from pathlib import Path

from _localsetup.tools.scrapling_helper import adapter_parser
from _localsetup.tools.scrapling_helper import adapter_state
from _localsetup.tools.scrapling_helper import config as scrapling_config
from _localsetup.tools.scrapling_helper import main as scrapling_main


def _temp_cfg(tmp_path: Path) -> scrapling_config.ScraplingConfig:
    return scrapling_config.ScraplingConfig(
        framework_root=tmp_path,
        cache_dir=tmp_path / ".cache" / "scrapling",
        logs_dir=tmp_path / "logs" / "scrapling",
        outputs_root=tmp_path / "scrapling_output",
        pipx_binary="pipx",
        docker_image="pyd4vinci/scrapling:latest",
    )


def test_parse_current_features_uses_help_output(monkeypatch) -> None:
    cfg = scrapling_config.load_config()

    def fake_run_help(_cfg, args):
        if args == ["--help"]:
            return "--help output\n--flag-x (deprecated)\n"
        if args == ["extract", "--help"]:
            return "extract help\n--extract-flag (experimental)\n"
        return "spider help\n"

    monkeypatch.setattr(adapter_parser, "_run_scrapling_help", fake_run_help)
    state = adapter_parser.parse_current_features(cfg)
    assert "top" in state.cli_commands
    assert "--flag-x" in state.flags
    assert "deprecated" in state.flags["--flag-x"]["tags"]
    assert "--extract-flag" in state.flags
    assert "experimental" in state.flags["--extract-flag"]["tags"]


def test_refresh_adapters_dry_run_does_not_write(tmp_path: Path, monkeypatch) -> None:
    cfg = _temp_cfg(tmp_path)

    def fake_parse(_cfg):
        return adapter_parser.AdapterState(
            supported_versions=[],
            cli_commands={"top": {"help": "help"}},
            fetch_modes={},
            spiders={},
            mcp_features={},
            flags={"--flag-x": {"description": "", "tags": []}},
        )

    monkeypatch.setattr(scrapling_main, "load_config", lambda: cfg)
    monkeypatch.setattr(scrapling_main, "parse_current_features", fake_parse, raising=False)
    result = scrapling_main.refresh_adapters(dry_run=True)
    assert result["applied"] is False
    assert "diff" in result
    assert "scrapling_status" in result["capabilities"]
    assert not adapter_state.state_path(cfg).exists()
    assert not adapter_state.capability_index_path(cfg).exists()


def test_refresh_adapters_apply_writes_state_and_capability_index(tmp_path: Path, monkeypatch) -> None:
    cfg = _temp_cfg(tmp_path)

    def fake_parse(_cfg):
        return adapter_parser.AdapterState(
            supported_versions=["test"],
            cli_commands={"top": {"help": "help"}},
            fetch_modes={"get": {"category": "http"}},
            spiders={},
            mcp_features={},
            flags={"--flag-x": {"description": "", "tags": []}},
        )

    monkeypatch.setattr(scrapling_main, "load_config", lambda: cfg)
    monkeypatch.setattr(scrapling_main, "parse_current_features", fake_parse, raising=False)

    result = scrapling_main.refresh_adapters(dry_run=False)

    assert result["applied"] is True
    assert adapter_state.state_path(cfg).is_file()
    assert adapter_state.capability_index_path(cfg).is_file()
    assert json.loads(adapter_state.capability_index_path(cfg).read_text(encoding="utf-8")) == result["capabilities"]


def test_packaged_capability_artifact_matches_builder_keys() -> None:
    root = Path(__file__).resolve().parents[2]
    cfg = scrapling_config.ScraplingConfig(
        framework_root=root,
        cache_dir=root / ".cache" / "scrapling",
        logs_dir=root / "logs" / "scrapling",
        outputs_root=root / "scrapling_output",
        pipx_binary="pipx",
        docker_image="pyd4vinci/scrapling:latest",
    )
    artifact = root / "_localsetup" / "tools" / "scrapling_helper" / "scrapling_capabilities.json"
    retired = root / "tools" / "scrapling_helper" / "scrapling_capabilities.json"

    data = json.loads(artifact.read_text(encoding="utf-8"))

    assert set(data) == set(scrapling_main.build_capability_index(cfg))
    assert not retired.exists()
