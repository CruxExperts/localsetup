from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .aliases import skill_alias
from .manifests import load_pack_config


@dataclass(frozen=True)
class SkillInfo:
    legacy_name: str
    name: str
    alias: str
    path: Path
    description: str
    packs: list[str]


def parse_skill_frontmatter(skill_md: Path) -> dict:
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}
    data = yaml.safe_load(text[4:end])
    return data if isinstance(data, dict) else {}


def selected_pack_names(repo_root: Path, requested_packs: list[str] | None) -> list[str]:
    pack = load_pack_config(repo_root)
    names = requested_packs or ["core"]
    unknown = [name for name in names if name not in pack.packs]
    if unknown:
        raise ValueError(f"unknown pack(s): {', '.join(sorted(unknown))}")
    return names


def selected_skill_names(repo_root: Path, requested_packs: list[str] | None) -> list[str]:
    pack = load_pack_config(repo_root)
    names = selected_pack_names(repo_root, requested_packs)
    selected: list[str] = []
    for pack_name in names:
        selected.extend(pack.packs.get(pack_name, []))
    return sorted(set(selected))


def load_skill_catalog(repo_root: Path) -> list[SkillInfo]:
    pack = load_pack_config(repo_root)
    reverse_packs: dict[str, list[str]] = {}
    for pack_name, skill_names in pack.packs.items():
        for skill_name in skill_names:
            reverse_packs.setdefault(skill_name, []).append(pack_name)

    skills_root = repo_root / "_localsetup" / "skills"
    catalog: list[SkillInfo] = []
    for skill_dir in sorted(skills_root.iterdir()):
        if not skill_dir.is_dir():
            continue
        frontmatter = parse_skill_frontmatter(skill_dir / "SKILL.md")
        legacy_name = skill_dir.name
        catalog.append(
            SkillInfo(
                legacy_name=legacy_name,
                name=str(frontmatter.get("name", "")),
                alias=skill_alias(legacy_name),
                path=skill_dir,
                description=str(frontmatter.get("description", "")),
                packs=sorted(reverse_packs.get(legacy_name, [])),
            )
        )
    return catalog


def validate_skill_catalog(repo_root: Path) -> list[str]:
    issues: list[str] = []
    for skill in load_skill_catalog(repo_root):
        if not skill.name:
            issues.append(f"missing frontmatter name: {skill.path}")
        elif skill.name != skill.legacy_name:
            issues.append(f"frontmatter name mismatch: {skill.path}")
        if not skill.description:
            issues.append(f"missing frontmatter description: {skill.path}")
        if not skill.alias.startswith("ls-"):
            issues.append(f"alias missing ls namespace: {skill.legacy_name}")
        if not skill.packs:
            issues.append(f"skill not assigned to a pack: {skill.legacy_name}")
    return issues
