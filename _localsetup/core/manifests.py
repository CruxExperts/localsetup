from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import PackConfig, PlatformConfig
from .paths import validate_home_scoped_path, validate_repo_relative_path
from .schema import validate_json_schema


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
    global_home = validate_home_scoped_path(str(global_data.get("home", "~/.local/share/localsetup")), "global.home")
    package_root = validate_home_scoped_path(
        str(global_data.get("package_root", global_data.get("root", "~/.local/share/localsetup/packages"))),
        "global.package_root",
    )
    registry_path = validate_home_scoped_path(
        str(global_data.get("registry", "~/.local/share/localsetup/registry.json")),
        "global.registry",
    )
    lockfile = validate_repo_relative_path(str(repo_data.get("lockfile", ".localsetup/lock.json")), "repo.lockfile")
    public_paths = [
        validate_repo_relative_path(str(v), "public_private.public_paths")
        for v in data.get("public_private", {}).get("public_paths", [])
    ]
    private_paths = [
        validate_repo_relative_path(str(v), "public_private.private_paths")
        for v in data.get("public_private", {}).get("private_paths", [])
    ]
    extensions = data.get("extensions", {})
    if extensions is None:
        extensions = {}
    if not isinstance(extensions, dict):
        raise ManifestError("extensions must be a mapping")
    raw_taxonomy = extensions.get("skill_taxonomy", {})
    if raw_taxonomy is None:
        raw_taxonomy = {}
    if not isinstance(raw_taxonomy, dict):
        raise ManifestError("extensions.skill_taxonomy must be a mapping")
    skill_taxonomy: dict[str, dict[str, Any]] = {}
    for skill_name, row in raw_taxonomy.items():
        if not isinstance(row, dict):
            raise ManifestError(f"extensions.skill_taxonomy.{skill_name} must be a mapping")
        skill_taxonomy[str(skill_name)] = dict(row)
    return PackConfig(
        pack_id=str(data["pack_id"]),
        namespace=str(data["namespace"]),
        version=int(data.get("version", 3)),
        global_home=global_home,
        package_root=package_root,
        registry_path=registry_path,
        global_root=package_root,
        global_registry=registry_path,
        lockfile=lockfile,
        optional_packs=[str(v) for v in data.get("optional_packs", [])],
        packs={str(k): [str(v) for v in values] for k, values in data.get("packs", {}).items()},
        workflow_packs={str(k): [str(v) for v in values] for k, values in data.get("workflow_packs", {}).items()},
        channels=[str(v) for v in data.get("distribution_channels", [])],
        public_paths=public_paths,
        private_paths=private_paths,
        skill_taxonomy=skill_taxonomy,
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
                verify_rules=[str(v) for v in entry.get("verify_rules", [])],
                rollback_targets=[
                    validate_repo_relative_path(str(v), f"platforms.{entry['id']}.rollback_targets")
                    for v in entry.get("rollback_targets", [])
                ],
            )
        )
    return out


def validate_manifest_schemas(repo_root: Path, *, require_jsonschema: bool = True) -> list[str]:
    issues: list[str] = []
    config_root = repo_root / "_localsetup" / "config"
    try:
        pack_data = _load_yaml(config_root / "pack.yaml")
        issues.extend(validate_json_schema(pack_data, config_root / "pack.schema.json", label="pack.yaml", required=require_jsonschema))
    except Exception as exc:
        issues.append(f"pack.yaml schema validation failed: {exc}")
    try:
        platforms_data = _load_yaml(config_root / "platforms.yaml")
        issues.extend(validate_json_schema(platforms_data, config_root / "platforms.schema.json", label="platforms.yaml", required=require_jsonschema))
    except Exception as exc:
        issues.append(f"platforms.yaml schema validation failed: {exc}")
    return issues
