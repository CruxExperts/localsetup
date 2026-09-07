from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .models import ClientRegistry


class ProjectionPathError(ValueError):
    pass


def platform_rows(registry: ClientRegistry) -> list[dict[str, Any]]:
    rows: list[tuple[int, dict[str, Any]]] = []
    for variant in registry.variants():
        compatibility = variant.data.get("compatibility")
        if compatibility is None:
            continue
        repo_skills = compatibility.get("repo_write_paths", variant.data["skills"]["repo"]["paths"])
        global_skills = compatibility.get("global_write_paths", variant.data["skills"]["global"]["paths"])
        rows.append(
            (
                int(compatibility["order"]),
                {
                    "id": str(compatibility["platform_id"]),
                    "repo_paths": list(repo_skills),
                    "global_paths": list(global_skills),
                    "native_config": str(compatibility["native_config"]),
                    "smoke_test_level": str(compatibility["smoke_test_level"]),
                    "verify_rules": list(compatibility["verify_rules"]),
                    "rollback_targets": list(repo_skills),
                },
            )
        )
    return [row for _order, row in sorted(rows, key=lambda item: (item[0], item[1]["id"]))]


def render_platforms_yaml(registry: ClientRegistry) -> bytes:
    lines = ["# Generated from ls/config/clients.yaml; do not edit.", "platforms:"]
    for row in platform_rows(registry):
        lines.extend(
            [
                f"  - id: {row['id']}",
                f"    repo_paths: {json.dumps(row['repo_paths'], ensure_ascii=False)}",
                f"    global_paths: {json.dumps(row['global_paths'], ensure_ascii=False)}",
                f"    native_config: {row['native_config']}",
                f"    smoke_test_level: {row['smoke_test_level']}",
                f"    verify_rules: {json.dumps(row['verify_rules'], ensure_ascii=False)}",
                f"    rollback_targets: {json.dumps(row['rollback_targets'], ensure_ascii=False)}",
                "",
            ]
        )
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def projection_path(repo_root: Path) -> Path:
    root = repo_root.absolute()
    if root.is_symlink():
        raise ProjectionPathError(f"repository root must not be a symlink: {root}")
    resolved_root = root.resolve(strict=True)
    parent = root / "ls" / "config"
    current = root
    for part in ("ls", "config"):
        current = current / part
        if current.is_symlink():
            raise ProjectionPathError(f"projection parent must not contain symlinks: {current}")
    resolved_parent = parent.resolve(strict=True)
    try:
        resolved_parent.relative_to(resolved_root)
    except ValueError as exc:
        raise ProjectionPathError(f"projection parent escapes repository root: {resolved_parent}") from exc
    path = parent / "platforms.yaml"
    if path.is_symlink():
        raise ProjectionPathError(f"projection destination must not be a symlink: {path}")
    return path


def projection_matches(repo_root: Path, registry: ClientRegistry) -> bool:
    path = projection_path(repo_root)
    return path.exists() and path.read_bytes() == render_platforms_yaml(registry)


def write_platforms_projection(repo_root: Path, registry: ClientRegistry) -> Path:
    path = projection_path(repo_root)
    expected = render_platforms_yaml(registry)
    if path.exists() and path.read_bytes() == expected:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    prior_mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    descriptor, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(raw_path)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(expected)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, prior_mode)
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)
    return path
