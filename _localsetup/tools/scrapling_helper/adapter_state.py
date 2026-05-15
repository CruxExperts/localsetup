"""
Purpose: Track Scrapling adapter state and supported features for self-refresh.
Created: 2026-03-16
Last Updated: 2026-03-16
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List

from .config import ScraplingConfig


@dataclass
class AdapterState:
    supported_versions: List[str]
    cli_commands: Dict[str, Dict[str, Any]]
    fetch_modes: Dict[str, Dict[str, Any]]
    spiders: Dict[str, Dict[str, Any]]
    mcp_features: Dict[str, Any]
    flags: Dict[str, Dict[str, Any]]


DEFAULT_STATE = AdapterState(
    supported_versions=[],
    cli_commands={},
    fetch_modes={},
    spiders={},
    mcp_features={},
    flags={},
)


def state_path(cfg: ScraplingConfig) -> Path:
    return cfg.framework_root / "_localsetup" / "tools" / "scrapling_helper" / "adapter_state.json"


def load_state(cfg: ScraplingConfig) -> AdapterState:
    path = state_path(cfg)
    if not path.exists():
        return DEFAULT_STATE
    data = json.loads(path.read_text(encoding="utf-8"))
    return AdapterState(
        supported_versions=data.get("supported_versions", []),
        cli_commands=data.get("cli_commands", {}),
        fetch_modes=data.get("fetch_modes", {}),
        spiders=data.get("spiders", {}),
        mcp_features=data.get("mcp_features", {}),
        flags=data.get("flags", {}),
    )


def save_state(cfg: ScraplingConfig, state: AdapterState) -> None:
    path = state_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")


def capability_index_path(cfg: ScraplingConfig) -> Path:
    return cfg.framework_root / "_localsetup" / "tools" / "scrapling_helper" / "scrapling_capabilities.json"


def save_capability_index(cfg: ScraplingConfig, index: Dict[str, Any]) -> None:
    path = capability_index_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, indent=2), encoding="utf-8")
