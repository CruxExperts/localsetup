"""Installation ownership is distinct from client discovery metadata."""
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class InstallationOwner:
    scope: Literal["repo", "personal"]
    root: str
    client: str

    def __post_init__(self):
        if self.scope not in {"repo", "personal"}:
            raise ValueError("Invalid installation owner scope")
        if not isinstance(self.root, str) or not Path(self.root).is_absolute():
            raise ValueError("Installation owner root must be absolute")
        if not isinstance(self.client, str) or not self.client:
            raise ValueError("Installation owner requires a client")

    def wire(self) -> dict[str, str]:
        return asdict(self)


def repository_owners(root: Path, clients: list[str]) -> list[dict[str, str]]:
    """One logical owner per client, independent of physical path coalescing."""
    owner_root = str(root.resolve(strict=False))
    return [InstallationOwner("repo", owner_root, client).wire()
            for client in sorted(set(clients))]


def resolve_skill_scope(target_root: Path, requested: str | None) -> str:
    """Omission retains a recorded scope; an old or fresh install defaults to repo."""
    from .lockfile import load_json
    from .paths import target_lockfile_path, legacy_target_lockfile_path
    scope = requested
    if scope is None:
        for path in (target_lockfile_path(target_root), legacy_target_lockfile_path(target_root)):
            if path.exists():
                record = load_json(path)
                if not isinstance(record, dict):
                    raise ValueError("Invalid installation lock")
                scope = record.get("skill_scope", "repo")
                break
        else:
            scope = "repo"
    if not isinstance(scope, str) or scope not in {"repo", "personal", "both"}:
        raise ValueError("Invalid skill scope")
    return scope


def validate_scope_request(target_root: Path, requested: str | None) -> bool:
    """Return whether a receipt exists; scope migration requires coordinated ownership."""
    from .paths import target_lockfile_path, legacy_target_lockfile_path
    recorded = any(path.exists() for path in (target_lockfile_path(target_root), legacy_target_lockfile_path(target_root)))
    if recorded and requested is not None and requested != resolve_skill_scope(target_root, None):
        raise ValueError("Changing recorded skill scope requires ownership migration, which is not yet qualified")
    return recorded
