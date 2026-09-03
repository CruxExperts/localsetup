"""Parse Scrapling CLI help into the conservative adapter-state model."""

from __future__ import annotations

from typing import Any, Dict

from .adapter_state import AdapterState
from .config import ScraplingConfig
from .host_env import apply_command_plan


def _run_scrapling_help(cfg: ScraplingConfig, args: list[str]) -> str:
    """Run host Scrapling help for one supported adapter-refresh surface."""
    cmd = ["scrapling", *args]
    result = apply_command_plan(cmd)
    if result.get("returncode", 1) != 0:
        return ""
    return result.get("stdout", "")


def _parse_help_output(text: str) -> Dict[str, Dict[str, Any]]:
    """Extract flags and conservative deprecation or experimental tags."""
    commands: Dict[str, Dict[str, Any]] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
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
    """Build adapter state from top-level and extraction help only."""
    top_help = _run_scrapling_help(cfg, ["--help"])
    extract_help = _run_scrapling_help(cfg, ["extract", "--help"])

    flags = _parse_help_output(top_help)
    flags.update(_parse_help_output(extract_help))

    fetch_modes = {
        "get": {"category": "http"},
        "post": {"category": "http"},
        "put": {"category": "http"},
        "delete": {"category": "http"},
        "fetch": {"category": "dynamic"},
        "stealthy-fetch": {"category": "stealth"},
    }

    return AdapterState(
        supported_versions=[],
        cli_commands={
            "top": {"help": top_help},
            "extract": {"help": extract_help},
        },
        fetch_modes=fetch_modes,
        spiders={},
        mcp_features={},
        flags=flags,
    )
