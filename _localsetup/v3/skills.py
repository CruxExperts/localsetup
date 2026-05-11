from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .aliases import legacy_skill_name, skill_alias
from .manifests import load_pack_config


@dataclass(frozen=True)
class SkillInfo:
    name: str
    legacy_name: str | None
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
    from .workflows import required_skills_for_workflows, selected_workflow_names

    selected.extend(required_skills_for_workflows(repo_root, selected_workflow_names(repo_root, requested_packs)))
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
        canonical_name = skill_alias(skill_dir.name)
        legacy_name = legacy_skill_name(canonical_name)
        catalog.append(
            SkillInfo(
                name=canonical_name,
                legacy_name=legacy_name if legacy_name != canonical_name else None,
                path=skill_dir,
                description=str(frontmatter.get("description", "")),
                packs=sorted(reverse_packs.get(canonical_name, [])),
            )
        )
    return catalog


def validate_skill_catalog(repo_root: Path) -> list[str]:
    issues: list[str] = []
    pack = load_pack_config(repo_root)
    skills_root = repo_root / "_localsetup" / "skills"
    canonical_names = {skill.name for skill in load_skill_catalog(repo_root)}

    for pack_name, skill_names in pack.packs.items():
        for skill_name in skill_names:
            if skill_name.startswith("localsetup-"):
                issues.append(f"pack uses legacy skill name: {pack_name}:{skill_name}")
            if skill_name not in canonical_names:
                issues.append(f"pack references missing skill: {pack_name}:{skill_name}")

    for skill in load_skill_catalog(repo_root):
        frontmatter = parse_skill_frontmatter(skill.path / "SKILL.md")
        frontmatter_name = str(frontmatter.get("name", ""))
        if skill.path.name.startswith("localsetup-"):
            issues.append(f"source skill directory uses legacy prefix: {skill.path}")
        if not skill.name.startswith("ls-"):
            issues.append(f"source skill directory missing ls namespace: {skill.path}")
        if not frontmatter_name:
            issues.append(f"missing frontmatter name: {skill.path}")
        elif frontmatter_name != skill.name:
            issues.append(f"frontmatter name mismatch: {skill.path}")
        if frontmatter_name.startswith("localsetup-"):
            issues.append(f"frontmatter name uses legacy prefix: {skill.path}")
        if not skill.description:
            issues.append(f"missing frontmatter description: {skill.path}")
        if not skill.packs:
            issues.append(f"skill not assigned to a pack: {skill.name}")
    return issues
