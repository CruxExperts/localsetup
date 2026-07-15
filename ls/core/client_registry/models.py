from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


def freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({str(key): freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class ClientVariant:
    family_id: str
    data: Mapping[str, Any]

    @property
    def variant_id(self) -> str:
        return str(self.data["id"])

    @property
    def key(self) -> str:
        return f"{self.family_id}/{self.variant_id}"


@dataclass(frozen=True)
class ClientFamily:
    family_id: str
    display_name: str
    variants: tuple[ClientVariant, ...]


@dataclass(frozen=True)
class ClientRegistry:
    schema_version: int
    families: tuple[ClientFamily, ...]

    def variants(self) -> tuple[ClientVariant, ...]:
        return tuple(variant for family in self.families for variant in family.variants)

    def variant(self, family_id: str, variant_id: str) -> ClientVariant:
        key = f"{family_id}/{variant_id}"
        for variant in self.variants():
            if variant.key == key:
                return variant
        raise KeyError(key)
