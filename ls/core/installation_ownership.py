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
