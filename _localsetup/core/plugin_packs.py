from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .manifests import ManifestError, load_pack_config
from .models import PluginPackConfig
from .paths import PathValidationError, repo_path, validate_repo_relative_path
from .schema import validate_json_schema
from .selection import resolve_package_selection


SUPPORTED_PLATFORMS = {"codex"}
PRIVATE_PATH_PREFIXES = (
    ".codex/",
    ".localsetup-maint/",
    "graphify-out/",
    "state/",
    "data/",
    "docs/",
)


@dataclass(frozen=True)
class ResolvedPluginPack:
    config: PluginPackConfig
    skills: list[str]
    workflows: list[str]

    @property
    def context_skill(self) -> str:
        return f"ls-plugin-{self.config.source_pack}-context"

    @property
    def all_skill_packages(self) -> list[str]:
        return [*self.skills, *self.workflows, self.context_skill]


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ManifestError(f"missing manifest: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ManifestError(f"manifest is not a mapping: {path}")
    return data


def _plugin_config_from_row(row: dict[str, Any]) -> PluginPackConfig:
    return PluginPackConfig(
        plugin_id=str(row["id"]),
        display_name=str(row["display_name"]),
        description=str(row["description"]),
        category=str(row["category"]),
        source_pack=str(row["source_pack"]),
        platforms={str(k): dict(v or {}) for k, v in row.get("platforms", {}).items()},
        extra_context_inputs=[str(v) for v in row.get("extra_context_inputs", [])],
    )


def load_plugin_pack_configs(repo_root: Path) -> list[PluginPackConfig]:
    data = _load_yaml(repo_root / "_localsetup" / "config" / "plugin-packs.yaml")
    return [_plugin_config_from_row(row) for row in data.get("plugin_packs", []) if isinstance(row, dict)]


def validate_plugin_pack_manifest(repo_root: Path, *, require_jsonschema: bool = True) -> list[str]:
    issues: list[str] = []
    config_root = repo_root / "_localsetup" / "config"
    try:
        data = _load_yaml(config_root / "plugin-packs.yaml")
        issues.extend(
            validate_json_schema(
                data,
                config_root / "plugin-packs.schema.json",
                label="plugin-packs.yaml",
                required=require_jsonschema,
            )
        )
    except Exception as exc:
        return [f"plugin-packs.yaml schema validation failed: {exc}"]

    try:
        pack = load_pack_config(repo_root)
        plugin_packs = load_plugin_pack_configs(repo_root)
    except Exception as exc:
        return [*issues, f"plugin-packs.yaml validation failed: {exc}"]

    seen_ids: set[str] = set()
    for plugin_pack in plugin_packs:
        if plugin_pack.plugin_id in seen_ids:
            issues.append(f"duplicate plugin pack id: {plugin_pack.plugin_id}")
        seen_ids.add(plugin_pack.plugin_id)
        if plugin_pack.source_pack not in pack.packs:
            issues.append(f"plugin pack references unknown source pack: {plugin_pack.plugin_id}:{plugin_pack.source_pack}")
        if "codex" not in plugin_pack.platforms:
            issues.append(f"plugin pack missing codex platform metadata: {plugin_pack.plugin_id}")
        for platform in plugin_pack.platforms:
            if platform not in SUPPORTED_PLATFORMS:
                issues.append(f"plugin pack references unsupported platform: {plugin_pack.plugin_id}:{platform}")
        for rel in plugin_pack.extra_context_inputs:
            try:
                _validated_context_input(repo_root, rel, pack.private_paths)
            except (PathValidationError, ValueError) as exc:
                issues.append(f"plugin pack context input invalid: {plugin_pack.plugin_id}:{rel}: {exc}")
    return issues


def _selected_plugin_configs(repo_root: Path, plugin_packs: list[str] | None) -> list[PluginPackConfig]:
    configs = load_plugin_pack_configs(repo_root)
    by_id = {cfg.plugin_id: cfg for cfg in configs}
    by_source = {cfg.source_pack: cfg for cfg in configs}
    if not plugin_packs:
        return configs
    selected: list[PluginPackConfig] = []
    unknown: list[str] = []
    for value in plugin_packs:
        cfg = by_id.get(value) or by_source.get(value)
        if cfg is None:
            unknown.append(value)
        elif cfg not in selected:
            selected.append(cfg)
    if unknown:
        raise ValueError(f"unknown plugin pack(s): {', '.join(sorted(unknown))}")
    return selected


def resolve_plugin_packs(repo_root: Path, plugin_packs: list[str] | None = None, *, platform: str = "codex") -> list[ResolvedPluginPack]:
    if platform not in SUPPORTED_PLATFORMS:
        raise ValueError(f"unsupported plugin platform: {platform}")
    resolved: list[ResolvedPluginPack] = []
    for config in _selected_plugin_configs(repo_root, plugin_packs):
        if platform not in config.platforms:
            continue
        selection = resolve_package_selection(repo_root, packs=[config.source_pack], preset="custom")
        resolved.append(ResolvedPluginPack(config=config, skills=selection.skills, workflows=selection.workflows))
    return resolved


def plugin_pack_catalog_payload(repo_root: Path) -> dict[str, Any]:
    packs = []
    for resolved in resolve_plugin_packs(repo_root, platform="codex"):
        packs.append(
            {
                "id": resolved.config.plugin_id,
                "display_name": resolved.config.display_name,
                "description": resolved.config.description,
                "category": resolved.config.category,
                "source_pack": resolved.config.source_pack,
                "platforms": sorted(resolved.config.platforms),
                "skills": resolved.skills,
                "workflows": resolved.workflows,
                "context_skill": resolved.context_skill,
            }
        )
    return {"schema_version": 1, "plugin_packs": packs, "count": len(packs)}


def plan_plugin_packs(repo_root: Path, plugin_packs: list[str] | None = None, *, platform: str = "codex") -> dict[str, Any]:
    resolved = resolve_plugin_packs(repo_root, plugin_packs, platform=platform)
    return {
        "ok": True,
        "platform": platform,
        "plugin_packs": [
            {
                "id": item.config.plugin_id,
                "display_name": item.config.display_name,
                "source_pack": item.config.source_pack,
                "skills": item.skills,
                "workflows": item.workflows,
                "context_skill": item.context_skill,
                "output_path": f"plugins/{item.config.plugin_id}",
            }
            for item in resolved
        ],
    }


def _is_private_path(rel: str, configured_private_paths: list[str]) -> bool:
    normalized = rel.rstrip("/")
    for private in [*configured_private_paths, *PRIVATE_PATH_PREFIXES]:
        private_norm = private.rstrip("/")
        if normalized == private_norm or normalized.startswith(private_norm + "/"):
            return True
    return False


def _validated_context_input(repo_root: Path, rel: str, private_paths: list[str]) -> Path:
    safe_rel = validate_repo_relative_path(rel, "plugin context input")
    if _is_private_path(safe_rel, private_paths):
        raise ValueError("path is private maintenance state")
    path = repo_path(repo_root, safe_rel, "plugin context input")
    if not path.is_file():
        raise ValueError("path is not a file")
    root = repo_root.resolve()
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("path resolves outside repository") from exc
    return path


def _copy_package_tree(source: Path, destination: Path, allowed_roots: list[Path], private_paths: list[str], repo_root: Path) -> None:
    if not source.is_dir():
        raise ValueError(f"missing package source: {source}")
    source_resolved = source.resolve(strict=True)
    if not any(source_resolved.is_relative_to(root.resolve(strict=True)) for root in allowed_roots):
        raise ValueError(f"package source outside allowed roots: {source}")
    for path in source.rglob("*"):
        rel = path.relative_to(repo_root).as_posix()
        if _is_private_path(rel, private_paths):
            raise ValueError(f"package includes private path: {rel}")
        if path.is_symlink():
            resolved = path.resolve(strict=True)
            if not any(resolved.is_relative_to(root.resolve(strict=True)) for root in allowed_roots):
                raise ValueError(f"package symlink resolves outside allowed roots: {rel}")
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, symlinks=True)


def _write_context_skill(repo_root: Path, destination: Path, resolved: ResolvedPluginPack) -> None:
    pack = load_pack_config(repo_root)
    destination.mkdir(parents=True, exist_ok=True)
    excerpts: list[str] = []
    for rel in resolved.config.extra_context_inputs:
        path = _validated_context_input(repo_root, rel, pack.private_paths)
        text = path.read_text(encoding="utf-8")
        excerpts.append(f"## Source: `{rel}`\n\n{text.strip()}\n")
    body = "\n".join(
        [
            "---",
            f"name: {resolved.context_skill}",
            f"description: Offline Localsetup context for the {resolved.config.display_name} Codex plugin pack.",
            "---",
            "",
            f"# {resolved.config.display_name} Context",
            "",
            "This generated skill carries minimal Localsetup orientation for a portable Codex plugin built outside the framework checkout.",
            "",
            f"- Plugin pack: `{resolved.config.plugin_id}`",
            f"- Source Localsetup pack: `{resolved.config.source_pack}`",
            f"- Included skills: {', '.join(f'`{name}`' for name in resolved.skills) or 'none'}",
            f"- Included workflows: {', '.join(f'`{name}`' for name in resolved.workflows) or 'none'}",
            "",
            *excerpts,
        ]
    )
    (destination / "SKILL.md").write_text(body.rstrip() + "\n", encoding="utf-8")


def build_codex_plugins(repo_root: Path, output_root: Path, plugin_packs: list[str] | None = None) -> dict[str, Any]:
    resolved_packs = resolve_plugin_packs(repo_root, plugin_packs, platform="codex")
    pack = load_pack_config(repo_root)
    version = (repo_root / "VERSION").read_text(encoding="utf-8").strip() if (repo_root / "VERSION").exists() else "0.0.0"
    output_root.mkdir(parents=True, exist_ok=True)
    plugins_root = output_root / "plugins"
    plugins_root.mkdir(parents=True, exist_ok=True)
    allowed_roots = [repo_root / "_localsetup" / "skills", repo_root / "_localsetup" / "workflows"]
    built: list[dict[str, Any]] = []

    for resolved in resolved_packs:
        plugin_dir = plugins_root / resolved.config.plugin_id
        skills_dir = plugin_dir / "skills"
        manifest_dir = plugin_dir / ".codex-plugin"
        if plugin_dir.exists():
            shutil.rmtree(plugin_dir)
        skills_dir.mkdir(parents=True, exist_ok=True)
        manifest_dir.mkdir(parents=True, exist_ok=True)
        for skill in resolved.skills:
            _copy_package_tree(repo_root / "_localsetup" / "skills" / skill, skills_dir / skill, allowed_roots, pack.private_paths, repo_root)
        for workflow in resolved.workflows:
            _copy_package_tree(repo_root / "_localsetup" / "workflows" / workflow, skills_dir / workflow, allowed_roots, pack.private_paths, repo_root)
        _write_context_skill(repo_root, skills_dir / resolved.context_skill, resolved)
        skill_names = resolved.all_skill_packages
        manifest = {
            "name": resolved.config.plugin_id,
            "version": version,
            "description": resolved.config.description,
            "author": "Localsetup",
            "skills": skill_names,
            "interface": resolved.config.platforms.get("codex", {}).get("interface", "v1"),
        }
        (manifest_dir / "plugin.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        readme = "\n".join(
            [
                f"# {resolved.config.display_name}",
                "",
                resolved.config.description,
                "",
                f"- Source pack: `{resolved.config.source_pack}`",
                f"- Skills: {len(resolved.skills)}",
                f"- Workflows: {len(resolved.workflows)}",
                f"- Generated context skill: `{resolved.context_skill}`",
                "",
            ]
        )
        (plugin_dir / "README.md").write_text(readme, encoding="utf-8")
        built.append({"id": resolved.config.plugin_id, "path": f"plugins/{resolved.config.plugin_id}", "skills": skill_names})

    marketplace = {"plugins": [{"name": item["id"], "path": f"./{item['path']}"} for item in built]}
    (output_root / "marketplace.json").write_text(json.dumps(marketplace, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"ok": True, "platform": "codex", "output": str(output_root), "plugins": built, "marketplace": str(output_root / "marketplace.json")}


def _plugin_child(root: Path, rel: str, field: str) -> Path:
    safe_rel = validate_repo_relative_path(rel, field)
    candidate = root / safe_rel
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=True))
    except ValueError as exc:
        raise PathValidationError(f"{field} resolves outside plugin root: {rel}") from exc
    return candidate


def _validate_plugin_tree(plugin_dir: Path, skills: list[str]) -> list[str]:
    issues: list[str] = []
    root = plugin_dir.resolve(strict=True)
    for path in plugin_dir.rglob("*"):
        rel = path.relative_to(plugin_dir).as_posix()
        if _is_private_path(rel, []):
            issues.append(f"Codex plugin contains private maintenance path: {path}")
        if path.is_symlink():
            try:
                resolved = path.resolve(strict=True)
            except FileNotFoundError:
                issues.append(f"Codex plugin contains broken symlink: {path}")
                continue
            try:
                resolved.relative_to(root)
            except ValueError:
                issues.append(f"Codex plugin symlink resolves outside plugin root: {path}")
    for skill in skills:
        try:
            skill_dir = _plugin_child(plugin_dir / "skills", skill, "Codex plugin skill path")
        except PathValidationError as exc:
            issues.append(str(exc))
            continue
        try:
            skill_dir.resolve(strict=False).relative_to(root)
        except ValueError:
            issues.append(f"Codex plugin skill path resolves outside plugin root: {skill}")
    return issues


def validate_codex_plugin_path(path: Path) -> dict[str, Any]:
    root = path.resolve()
    plugin_dirs: list[Path]
    if (root / "marketplace.json").is_file():
        try:
            marketplace = json.loads((root / "marketplace.json").read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return {"ok": False, "issues": [f"invalid marketplace JSON: {root / 'marketplace.json'}: {exc}"], "plugins": []}
        if not isinstance(marketplace, dict):
            return {"ok": False, "issues": [f"marketplace JSON must be an object: {root / 'marketplace.json'}"], "plugins": []}
        marketplace_plugins = marketplace.get("plugins", [])
        if not isinstance(marketplace_plugins, list):
            return {"ok": False, "issues": [f"marketplace plugins must be a list: {root / 'marketplace.json'}"], "plugins": []}
        plugin_dirs = []
        seen_names: set[str] = set()
        seen_paths: set[Path] = set()
        marketplace_issues: list[str] = []
        for row in marketplace_plugins:
            if not isinstance(row, dict):
                marketplace_issues.append(f"marketplace plugin entry must be an object: {row!r}")
                continue
            name = str(row.get("name", "")).strip()
            rel = str(row.get("path", "")).removeprefix("./")
            if not name:
                marketplace_issues.append("marketplace plugin entry missing name")
            elif name in seen_names:
                marketplace_issues.append(f"duplicate marketplace plugin name: {name}")
            seen_names.add(name)
            try:
                plugin_dir = _plugin_child(root, rel, "marketplace plugin path")
            except PathValidationError as exc:
                marketplace_issues.append(str(exc))
                continue
            if plugin_dir in seen_paths:
                marketplace_issues.append(f"duplicate marketplace plugin path: {rel}")
            seen_paths.add(plugin_dir)
            plugin_dirs.append(plugin_dir)
    else:
        marketplace_issues = []
        plugin_dirs = [root]

    issues: list[str] = [*marketplace_issues]
    plugins: list[dict[str, Any]] = []
    for plugin_dir in plugin_dirs:
        manifest_path = plugin_dir / ".codex-plugin" / "plugin.json"
        if not manifest_path.is_file():
            issues.append(f"missing Codex plugin manifest: {manifest_path}")
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            issues.append(f"invalid Codex plugin manifest JSON: {manifest_path}: {exc}")
            continue
        if not isinstance(manifest, dict):
            issues.append(f"Codex plugin manifest must be an object: {manifest_path}")
            continue
        required = {"name", "version", "description", "author", "skills", "interface"}
        missing = sorted(required - set(manifest))
        if missing:
            issues.append(f"Codex plugin manifest missing fields: {manifest_path}: {', '.join(missing)}")
        skills = manifest.get("skills", [])
        if not isinstance(skills, list) or not all(isinstance(item, str) and item for item in skills):
            issues.append(f"Codex plugin manifest skills must be a string list: {manifest_path}")
            skills = []
        for skill in skills:
            if not (plugin_dir / "skills" / skill / "SKILL.md").is_file():
                issues.append(f"Codex plugin missing skill package: {plugin_dir / 'skills' / skill}")
        issues.extend(_validate_plugin_tree(plugin_dir, skills))
        plugins.append({"name": manifest.get("name"), "path": str(plugin_dir), "skills": skills})
    return {"ok": not issues, "issues": issues, "plugins": plugins}
