from __future__ import annotations

from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class Finding:
    id: str
    severity: str
    category: str
    path: str
    line: int | None
    message: str
    expected: Any = None
    actual: Any = None
    source: str = ""
    fix_scope: str = "manual_review"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "severity": self.severity,
            "category": self.category,
            "path": self.path,
            "line": self.line,
            "message": self.message,
            "expected": self.expected,
            "actual": self.actual,
            "source": self.source,
            "fix_scope": self.fix_scope,
        }
