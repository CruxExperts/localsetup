from __future__ import annotations

import tarfile
from pathlib import Path

from .boundary import scan_tar_for_leaks
from .manifests import load_pack_config
from .paths import repo_path
from .source import source_commit


def build_public_artifact(repo_root: Path, output_path: Path) -> dict:
    pack = load_pack_config(repo_root)
    added: list[str] = []

    def is_skill_runtime_data(path_parts: list[str]) -> bool:
        """Exclude generated skill runtime state, not skill source assets."""
        return (
            len(path_parts) >= 5
            and path_parts[0] == "_localsetup"
            and path_parts[1] == "skills"
            and path_parts[3:5] == ["scripts", "data"]
        )

    def include_public(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo | None:
        name = tarinfo.name.strip("/")
        parts = set(name.split("/"))
        path_parts = name.split("/")
        if (
            "__pycache__" in parts
            or ".cache" in parts
            or ".pytest_cache" in parts
            or ".mypy_cache" in parts
            or ".ruff_cache" in parts
            or name.endswith((".pyc", ".pyo"))
        ):
            return None
        if is_skill_runtime_data(path_parts):
            return None
        for private in pack.private_paths:
            private_name = private.rstrip("/")
            if name == private_name or name.startswith(private_name + "/"):
                return None
        added.append(name)
        return tarinfo

    with tarfile.open(output_path, "w:gz") as tar:
        for rel in pack.public_paths:
            src = repo_path(repo_root, rel, "public path")
            if src.exists():
                tar.add(src, arcname=rel, filter=include_public)

    leaks = scan_tar_for_leaks(output_path, pack.private_paths)
    return {
        "artifact": str(output_path),
        "files": added,
        "leaks": leaks,
        "manifest": {
            "pack_id": pack.pack_id,
            "version": pack.version,
            "source_commit": source_commit(repo_root),
            "public_paths": pack.public_paths,
        },
    }
