from __future__ import annotations

from pathlib import Path
import re


def legacy_skill_name(skill_name: str) -> str:
    return skill_name.replace("ls-", "localsetup-", 1) if skill_name.startswith("ls-") else skill_name


def skill_alias(skill_name: str) -> str:
    return skill_name.replace("localsetup-", "ls-", 1) if skill_name.startswith("localsetup-") else skill_name


def collect_skill_aliases(skills_root: Path) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for skill_dir in sorted(skills_root.iterdir()):
        if not skill_dir.is_dir():
            continue
        canonical_name = skill_alias(skill_dir.name)
        aliases[legacy_skill_name(canonical_name)] = canonical_name

    migration_map = skills_root.parent / "docs" / "migration" / "v2-to-v3-skill-map.md"
    if migration_map.exists():
        for old_name, new_name in re.findall(r"`(localsetup-[^`]+)`\s*\|\s*`(ls-[^`]+)`", migration_map.read_text(encoding="utf-8")):
            aliases.setdefault(old_name, new_name)
    return aliases
