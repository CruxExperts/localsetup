"""Copy package assets while omitting Python runtime bytecode."""

from __future__ import annotations

import shutil
from pathlib import Path


def copy_source_tree(source: Path, destination: Path) -> None:
    source_resolved = source.resolve(strict=True)
    for path in sorted(source.rglob("*")):
        rel = path.relative_to(source)
        if "__pycache__" in rel.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        if path.is_symlink():
            resolved = path.resolve(strict=True)
            try:
                resolved.relative_to(source_resolved)
            except ValueError as exc:
                raise ValueError(f"package symlink resolves outside package source: {path}") from exc
        target = destination / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
