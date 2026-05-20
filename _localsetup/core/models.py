from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SourceLayout:
    source_root: Path

    @property
    def framework_root(self) -> Path:
        return self.source_root / "_localsetup"


@dataclass(frozen=True)
class GlobalLayout:
    localsetup_home: Path
    package_root: Path
    registry_path: Path

    @property
    def venv_path(self) -> Path:
        return self.localsetup_home / "venv"

    @property
    def cache_root(self) -> Path:
        return self.localsetup_home / "cache"

    @property
    def state_root(self) -> Path:
        return self.localsetup_home / "state"

    @property
    def logs_root(self) -> Path:
        return self.localsetup_home / "logs"


@dataclass(frozen=True)
class TargetLayout:
    target_root: Path

    @property
    def state_root(self) -> Path:
        return self.target_root / ".localsetup"

    @property
    def lockfile_path(self) -> Path:
        return self.state_root / "lock.json"

    @property
    def legacy_lockfile_path(self) -> Path:
        return self.target_root / "localsetup.lock.json"

    @property
    def journal_root(self) -> Path:
        return self.state_root / "install-journal"

    @property
    def backup_root(self) -> Path:
        return self.state_root / "backups"

    @property
    def context_index_root(self) -> Path:
        return self.state_root / "context-index"


@dataclass
class PackConfig:
    pack_id: str
    namespace: str
    version: int
    global_home: str
    package_root: str
    registry_path: str
    global_root: str
    global_registry: str
    lockfile: str
    optional_packs: list[str] = field(default_factory=list)
    packs: dict[str, list[str]] = field(default_factory=dict)
    workflow_packs: dict[str, list[str]] = field(default_factory=dict)
    channels: list[str] = field(default_factory=list)
    public_paths: list[str] = field(default_factory=list)
    private_paths: list[str] = field(default_factory=list)
    skill_taxonomy: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class PlatformConfig:
    platform_id: str
    repo_paths: list[str]
    global_paths: list[str]
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
