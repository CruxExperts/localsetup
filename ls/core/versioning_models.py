"""Data models for Localsetup version planning."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SemVer:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: str) -> "SemVer":
        match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", value.strip())
        if not match:
            raise ValueError(f"invalid semantic version: {value!r}")
        return cls(*(int(part) for part in match.groups()))

    def bump(self, bump_type: str) -> "SemVer":
        if bump_type == "major":
            return SemVer(self.major + 1, 0, 0)
        if bump_type == "minor":
            return SemVer(self.major, self.minor + 1, 0)
        if bump_type == "patch":
            return SemVer(self.major, self.minor, self.patch + 1)
        if bump_type == "none":
            return self
        raise ValueError(f"unknown bump type: {bump_type}")

    @property
    def major_minor(self) -> str:
        return f"{self.major}.{self.minor}"

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True)
class CommitInfo:
    sha: str
    subject: str
    body: str
