from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ClientStateError(ValueError):
    """A stable, user-correctable client-state failure."""

    def __init__(self, message: str, *, code: str = "client_state_error") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class GitContext:
    root: Path
    exclude_path: Path
    head: str | None
    ref: str | None


@dataclass(frozen=True)
class StateLocation:
    client: str
    scope: str
    requested_scope: str
    repo_root: Path
    cwd: Path
    home: Path
    owner_root: Path
    owner_identity: tuple[int, int] | None
    root: Path
    root_identity: tuple[int, int] | None
    state_path: str
    git: GitContext | None
    registry_schema_version: int
    variant_digest: str

    def payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "client": self.client,
            "ok": True,
            "scope": self.scope,
            "state_path": self.state_path,
            "registry": {
                "schema_version": self.registry_schema_version,
                "variant_digest": self.variant_digest,
            },
        }
        if self.git:
            payload["repository"] = {
                "head": self.git.head,
                "ref": self.git.ref,
                "root": ".",
            }
        return payload
