"""
Purpose: Parse Scrapling CLI help and docs into a structured AdapterState feature model.
Created: 2026-03-16
Last Updated: 2026-03-16
"""

from __future__ import annotations

import json
from typing import Any, Dict

from .adapter_state import AdapterState
from .config import ScraplingConfig
from .docker_env import build_scrapling_docker_command
from .host_env import apply_command_plan


def _run_scrapling_help(cfg: ScraplingConfig, args: list[str]) -> str:
    """
    Run `scrapling` with the given help args on the host. Docker integration
    can be added later if needed by swapping command construction.
    """
    cmd = ["scrapling", *args]
    result = apply_command_plan(cmd)
    if result.get("returncode", 1) != 0:
        return ""
    return result.get("stdout", "")


def _parse_help_output(text: str) -> Dict[str, Dict[str, Any]]:
    """
    Extremely lightweight help parser that extracts flags and tags potential
    deprecations or experimental options based on substrings.
    """
    commands: Dict[str, Dict[str, Any]] = {}
    current_section: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.endswith("commands:") or stripped.endswith("options:"):
            current_section = stripped.lower()
            continue
        if stripped.startswith("-") or stripped.startswith("--"):
            flag_name = stripped.split()[0]
            entry = commands.setdefault(flag_name, {"description": stripped, "tags": []})
            lowered = stripped.lower()
            if "deprecated" in lowered:
                entry["tags"].append("deprecated")
            if "experimental" in lowered:
                entry["tags"].append("experimental")
    return commands


def parse_current_features(cfg: ScraplingConfig) -> AdapterState:
    """
    Build an AdapterState from the current Scrapling CLI help output.
    This is intentionally conservative but captures enough structure to
    drive diffing and adapter refresh reporting.
    """
    top_help = _run_scrapling_help(cfg, ["--help"])
    extract_help = _run_scrapling_help(cfg, ["extract", "--help"])
    spider_help = _run_scrapling_help(cfg, ["spider", "--help"])

    flags = _parse_help_output(top_help)
    flags.update(_parse_help_output(extract_help))
    flags.update(_parse_help_output(spider_help))

    fetch_modes = {
        # Core HTTP fetchers from the cheat sheet.
        "get": {"category": "http"},
        "post": {"category": "http"},
        "put": {"category": "http"},
        "delete": {"category": "http"},
        # Dynamic and stealthy browser-based modes.
        "fetch": {"category": "dynamic"},
        "stealthy-fetch": {"category": "stealth"},
    }

    spiders = {
        # The CLI exposes a generic spider runner; specific spider names live in user projects.
        "spider": {"help": spider_help},
    }

    return AdapterState(
        supported_versions=[],
        cli_commands={
            "top": {"help": top_help},
            "extract": {"help": extract_help},
            "spider": {"help": spider_help},
        },
        fetch_modes=fetch_modes,
        spiders=spiders,
        mcp_features={},
        flags=flags,
    )
