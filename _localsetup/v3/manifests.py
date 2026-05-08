from __future__ import annotations

from pathlib import Path

import yaml

from .models import PackConfig, PlatformConfig
from .paths import validate_home_scoped_path, validate_repo_relative_path


class ManifestError(RuntimeError):
    pass


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise ManifestError(f"missing manifest: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ManifestError(f"manifest is not a mapping: {path}")
    return data


def load_pack_config(repo_root: Path) -> PackConfig:
    data = _load_yaml(repo_root / "_localsetup" / "config" / "pack.yaml")
    global_data = data.get("global", {})
    repo_data = data.get("repo", {})
    global_root = validate_home_scoped_path(str(global_data["root"]), "global.root")
    global_registry = validate_home_scoped_path(str(global_data["registry"]), "global.registry")
    lockfile = validate_repo_relative_path(str(repo_data.get("lockfile", "localsetup.lock.json")), "repo.lockfile")
    public_paths = [
        validate_repo_relative_path(str(v), "public_private.public_paths")
        for v in data.get("public_private", {}).get("public_paths", [])
    ]
    private_paths = [
        validate_repo_relative_path(str(v), "public_private.private_paths")
        for v in data.get("public_private", {}).get("private_paths", [])
    ]
    return PackConfig(
        pack_id=str(data["pack_id"]),
        namespace=str(data["namespace"]),
        version=int(data.get("version", 3)),
        global_root=global_root,
        global_registry=global_registry,
        lockfile=lockfile,
        optional_packs=[str(v) for v in data.get("optional_packs", [])],
        packs={str(k): [str(v) for v in values] for k, values in data.get("packs", {}).items()},
        channels=[str(v) for v in data.get("distribution_channels", [])],
        public_paths=public_paths,
        private_paths=private_paths,
    )


def load_platforms(repo_root: Path) -> list[PlatformConfig]:
    data = _load_yaml(repo_root / "_localsetup" / "config" / "platforms.yaml")
    entries = data.get("platforms", [])
    if not isinstance(entries, list):
        raise ManifestError("platforms must be a list")
    out: list[PlatformConfig] = []
    for entry in entries:
        out.append(
            PlatformConfig(
                platform_id=str(entry["id"]),
                repo_paths=[validate_repo_relative_path(str(v), f"platforms.{entry['id']}.repo_paths") for v in entry.get("repo_paths", [])],
                global_paths=[validate_home_scoped_path(str(v), f"platforms.{entry['id']}.global_paths") for v in entry.get("global_paths", [])],
                memory_paths=[validate_home_scoped_path(str(v), f"platforms.{entry['id']}.memory_paths") for v in entry.get("memory_paths", [])],
                verify_rules=[str(v) for v in entry.get("verify_rules", [])],
                rollback_targets=[
                    validate_repo_relative_path(str(v), f"platforms.{entry['id']}.rollback_targets")
                    for v in entry.get("rollback_targets", [])
                ],
            )
        )
    return out
