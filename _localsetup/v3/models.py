from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PackConfig:
    pack_id: str
    namespace: str
    version: int
    global_root: str
    global_registry: str
    lockfile: str
    optional_packs: list[str] = field(default_factory=list)
    packs: dict[str, list[str]] = field(default_factory=dict)
    workflow_packs: dict[str, list[str]] = field(default_factory=dict)
    channels: list[str] = field(default_factory=list)
    public_paths: list[str] = field(default_factory=list)
    private_paths: list[str] = field(default_factory=list)


@dataclass
class PlatformConfig:
    platform_id: str
    repo_paths: list[str]
    global_paths: list[str]
    memory_paths: list[str]
    verify_rules: list[str]
    rollback_targets: list[str]


@dataclass
class PlanAction:
    kind: str
    path: Path
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class DeployPlan:
    actions: list[PlanAction]
    rollback_metadata: dict[str, Any]
