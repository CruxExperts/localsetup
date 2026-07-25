from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


class DomainShapesError(ValueError):
    """Base error for domain-shape loading, validation, and compilation."""

    def __init__(self, message: str, *, issues: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.issues = issues or (message,)


class DomainConfigError(DomainShapesError):
    """Raised when a domain-shapes configuration is unreadable or invalid."""


class DomainCompileError(DomainShapesError):
    """Raised when a domain cannot be safely compiled."""


@dataclass(frozen=True, slots=True)
class DomainRoot:
    kind: Literal["file", "tree"]
    path: str


@dataclass(frozen=True, slots=True)
class PatternSet:
    glob: tuple[str, ...] = ()
    regex: tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        return not self.glob and not self.regex


@dataclass(frozen=True, slots=True)
class DomainDefinition:
    domain_id: str
    roots: tuple[DomainRoot, ...]
    include: PatternSet
    exclude: PatternSet
    max_files: int
    max_bytes: int


@dataclass(frozen=True, slots=True)
class DomainShapesConfig:
    schema_version: int
    domains: tuple[DomainDefinition, ...]

    def domain(self, domain_id: str) -> DomainDefinition:
        for definition in self.domains:
            if definition.domain_id == domain_id:
                return definition
        raise DomainConfigError(
            f"unknown domain {domain_id!r}; available domains: "
            f"{', '.join(item.domain_id for item in self.domains) or '<none>'}",
            issues=(f"unknown domain: {domain_id}",),
        )


__all__ = [
    "DomainCompileError",
    "DomainConfigError",
    "DomainDefinition",
    "DomainRoot",
    "DomainShapesConfig",
    "DomainShapesError",
    "PatternSet",
]
