"""Target platform and package inference for repair."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .adapters import adapter_targets
from .manifests import load_pack_config, load_platforms
from .repair_common import _known_package_names, _normalize_package_names
from .selection import resolve_package_selection

HISTORICAL_ADAPTERS = {
    "codex": [".codex/skills"],
}

def _extract_list(payload: dict[str, Any], *keys: str) -> list[str]:
    values: list[str] = []
    for key in keys:
        raw = payload.get(key)
        if isinstance(raw, list):
            values.extend(str(item) for item in raw)
    return values

def _path_hints_platform(path_text: str) -> str | None:
    normalized = path_text.replace("\\", "/")
    if ".agents/skills" in normalized or ".codex/skills" in normalized:
        return "codex"
    if ".claude/skills" in normalized:
        return "claude-code"
    if ".cursor/skills" in normalized:
        return "cursor"
    if ".kilo/skills" in normalized:
        return "kilo"
    if ".opencode/skills" in normalized:
        return "opencode"
    if ".openclaw/skills" in normalized:
        return "openclaw"
    return None

def _visible_names(path: Path) -> list[str]:
    if not path.is_dir() or path.is_symlink():
        return []
    return sorted(child.name for child in path.iterdir() if not child.name.startswith("."))

def _visible_package_entries(path: Path) -> list[dict[str, Any]]:
    if not path.is_dir() or path.is_symlink():
        return []
    entries: list[dict[str, Any]] = []
    for child in sorted(path.iterdir()):
        if child.name.startswith("."):
            continue
        entries.append(
            {
                "name": child.name,
                "path": str(child),
                "custom_skill": child.is_dir() and not child.is_symlink() and (child / "SKILL.md").is_file(),
            }
        )
    return entries

def _infer_platforms(
    source_root: Path,
    target_root: Path,
    modern_lock: dict[str, Any],
    legacy_lock: dict[str, Any],
    explicit_platforms: list[str] | None,
) -> tuple[list[str], list[str]]:
    if explicit_platforms is not None:
        return sorted(set(explicit_platforms)), ["explicit --platforms"]
    selected: set[str] = set()
    reasons: list[str] = []
    for value in _extract_list(modern_lock, "platforms"):
        selected.add(value)
    if selected:
        reasons.append(".localsetup/lock.json platforms")
    for value in _extract_list(legacy_lock, "platforms", "tools"):
        selected.add(value)
    for value in _extract_list(legacy_lock, "adapter_state", "adapter_paths"):
        platform_id = _path_hints_platform(value)
        if platform_id:
            selected.add(platform_id)
    if selected:
        reasons.append("legacy lock selectors")
    known_platforms = {platform.platform_id: platform for platform in load_platforms(source_root)}
    if selected:
        return sorted(selected & set(known_platforms)), sorted(set(reasons))
    for platform in known_platforms.values():
        for rel in platform.repo_paths:
            if (target_root / rel).exists() or (target_root / rel).is_symlink():
                selected.add(platform.platform_id)
                reasons.append(f"existing adapter path {rel}")
    for platform_id, rel_paths in HISTORICAL_ADAPTERS.items():
        for rel in rel_paths:
            if (target_root / rel).exists() or (target_root / rel).is_symlink():
                selected.add(platform_id)
                reasons.append(f"historical adapter path {rel}")
    known_ids = set(known_platforms)
    return sorted(selected & known_ids), sorted(set(reasons))

def _infer_attach_mode(modern_lock: dict[str, Any]) -> tuple[str, str]:
    if modern_lock.get("attach_mode") == "portable":
        return "portable", "modern lock attach_mode"
    return "symlink", "default modern scoped symlink adapters"

def _infer_packages(
    source_root: Path,
    target_root: Path,
    home: Path,
    platform_ids: list[str],
    modern_lock: dict[str, Any],
    legacy_lock: dict[str, Any],
    decisions: list[dict],
) -> dict[str, Any]:
    values: list[str] = []
    reasons: list[str] = []
    custom_repo_skills: list[dict[str, str]] = []
    for key in ("repo_packages", "adapter_packages", "repo_skills"):
        extracted = _extract_list(modern_lock, key)
        if extracted:
            values.extend(extracted)
            reasons.append(f"modern lock {key}")
    extracted_workflows = _extract_list(modern_lock, "repo_workflows", "workflows")
    if extracted_workflows:
        values.extend(extracted_workflows)
        reasons.append("modern lock repo_workflows/workflows")
    for key in ("repo_packages", "adapter_packages", "installed_skills", "skills", "packs"):
        extracted = _extract_list(legacy_lock, key)
        if extracted:
            values.extend(extracted)
            reasons.append(f"legacy lock {key}")
    extracted_legacy_workflows = _extract_list(legacy_lock, "repo_workflows", "workflows", "installed_workflows")
    if extracted_legacy_workflows:
        values.extend(extracted_legacy_workflows)
        reasons.append("legacy lock repo_workflows/workflows")
    pack_names = set(load_pack_config(source_root).packs)
    values = [value for value in values if value not in pack_names]
    metadata_values = bool(values)
    known_packages = _known_package_names(source_root)
    for target in adapter_targets(source_root, home, platform_ids=platform_ids, target_root=target_root):
        entries = _visible_package_entries(target["repo_path"])
        visible = [entry["name"] for entry in entries if entry["name"] in known_packages]
        custom_repo_skills.extend(
            {"name": entry["name"], "path": entry["path"]}
            for entry in entries
            if entry["name"] not in known_packages and entry["custom_skill"]
        )
        if visible and not metadata_values:
            values.extend(visible)
            reasons.append(f"visible adapter packages at {target['repo_path'].relative_to(target_root)}")
    for rel_paths in HISTORICAL_ADAPTERS.values():
        for rel in rel_paths:
            entries = _visible_package_entries(target_root / rel)
            visible = [entry["name"] for entry in entries if entry["name"] in known_packages]
            custom_repo_skills.extend(
                {"name": entry["name"], "path": entry["path"]}
                for entry in entries
                if entry["name"] not in known_packages and entry["custom_skill"]
            )
            if visible and not metadata_values:
                values.extend(visible)
                reasons.append(f"visible historical adapter packages at {rel}")
    normalized = _normalize_package_names(source_root, values, decisions)
    if normalized["repo_packages"]:
        normalized["package_reasons"] = sorted(set(reasons))
        normalized["custom_repo_skills"] = sorted(custom_repo_skills, key=lambda item: (item["name"], item["path"]))
        normalized["confidence"] = "high"
        return normalized
    default = resolve_package_selection(source_root, preset="core", target_root=target_root).packages
    default_normalized = _normalize_package_names(source_root, default, decisions)
    default_normalized["package_reasons"] = ["default core selection"]
    default_normalized["custom_repo_skills"] = sorted(custom_repo_skills, key=lambda item: (item["name"], item["path"]))
    default_normalized["confidence"] = "default"
    return default_normalized
