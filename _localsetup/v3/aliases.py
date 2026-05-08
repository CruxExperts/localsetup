from __future__ import annotations

from pathlib import Path


def skill_alias(skill_name: str) -> str:
    return skill_name.replace("localsetup-", "ls-", 1) if skill_name.startswith("localsetup-") else skill_name


def collect_skill_aliases(skills_root: Path) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for skill_dir in sorted(skills_root.iterdir()):
        if not skill_dir.is_dir():
            continue
        old_name = skill_dir.name
        aliases[old_name] = skill_alias(old_name)
    return aliases
