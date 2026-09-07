"""Bounded identity inventory; never predict OpenCode's concurrent loader winner."""
import os
from pathlib import Path

from .amp_preflight import _name


def skill_sources(root: Path, budget: list[int], ancestors=()):
    """Enumerate recursive skill metadata without following traversal cycles."""
    if not root.exists() and not root.is_symlink():
        return
    if not root.is_dir():
        raise ValueError('skill root is not a directory')
    resolved = root.resolve(strict=True)
    if resolved in ancestors or len(ancestors) >= 32:
        raise ValueError('skill traversal cycle or depth limit')
    metadata = root / 'SKILL.md'
    if metadata.exists() or metadata.is_symlink():
        yield metadata, _name(metadata)
    with os.scandir(root) as entries:
        for entry in entries:
            budget[0] += 1
            if budget[0] > 4096:
                raise ValueError('skill traversal exceeds 4096 entries')
            if entry.is_dir():
                yield from skill_sources(Path(entry.path), budget, (*ancestors, resolved))
            elif entry.is_symlink() and not entry.is_file():
                raise ValueError('unresolved skill link')


def conflicting_sources(roots: list[Path], intended: dict[str, set[Path]]) -> list[Path]:
    """Find selected-name conflicts; callers own roots, policy and error handling.

    Intended entries are exact metadata files, including future destinations and
    explicitly accepted source identities. Equal file bytes are not equivalence.
    Unknown or malformed inventory raises without returning a partial success.
    """
    accepted = {name: {path.resolve(strict=False) for path in paths}
                for name, paths in intended.items()}
    conflicts = []
    budget = [0]
    seen = set()
    for root in dict.fromkeys(roots):
        for metadata, name in skill_sources(root, budget):
            if name not in accepted:
                continue
            identity = metadata.resolve(strict=True)
            if identity in seen:
                continue
            seen.add(identity)
            if identity not in accepted[name]:
                conflicts.append(metadata)
    return conflicts
