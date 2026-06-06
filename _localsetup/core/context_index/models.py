from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ContextIndexError(RuntimeError):
    def __init__(self, code: str, message: str, recommended_action: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.recommended_action = recommended_action


@dataclass(frozen=True)
class Runtime:
    repo_root: Path
    home: Path
    config: dict[str, Any]
    context: dict[str, str]
    db_path: Path
    scope: str
