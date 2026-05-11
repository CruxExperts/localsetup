from __future__ import annotations

import json
from pathlib import Path

from .aliases import collect_skill_aliases
from .baseline import implementation_file_map
from .manifests import load_platforms
from .skills import load_skill_catalog
from .workflows import load_workflow_catalog, workflow_catalog_payload


def generate_alias_outputs(repo_root: Path) -> dict:
    aliases = collect_skill_aliases(repo_root / "_localsetup" / "skills")
    aliases_path = repo_root / "_localsetup" / "docs" / "_generated" / "skill_aliases.json"
    aliases_path.parent.mkdir(parents=True, exist_ok=True)
    aliases_path.write_text(json.dumps(aliases, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    migration_md = repo_root / "_localsetup" / "docs" / "migration" / "v2-to-v3-skill-map.md"
    version_file = repo_root / "VERSION"
    version = version_file.read_text(encoding="utf-8").strip() if version_file.exists() else "3.0.0"
    major_minor = ".".join(version.split(".")[:2]) if "." in version else version
    lines = [
        "---",
        "status: ACTIVE",
        f"version: {major_minor}",
        "---",
        "",
        "# v2 to v3 Skill Map",
        "",
        "| v2 | v3 |",
        "|---|---|",
    ]
    for old, new in sorted(aliases.items()):
        lines.append(f"| `{old}` | `{new}` |")
    migration_md.parent.mkdir(parents=True, exist_ok=True)
    migration_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    platforms_md = repo_root / "_localsetup" / "docs" / "_generated" / "platform-adapters.md"
    platform_lines = [
        "# Platform Adapters",
        "",
        "Repo adapter paths are attached only when selected with `--tools` or `--platforms`; a selector-free install is global-only.",
        "",
        "| Platform | Repo Paths | Verify Rules |",
        "|---|---|---|",
    ]
    for platform in load_platforms(repo_root):
        platform_lines.append(
            f"| `{platform.platform_id}` | `{', '.join(platform.repo_paths)}` | `{', '.join(platform.verify_rules)}` |"
        )
    platforms_md.write_text("\n".join(platform_lines) + "\n", encoding="utf-8")

    packs_md = repo_root / "_localsetup" / "docs" / "_generated" / "skill-packs.md"
    pack_lines = ["# Skill And Workflow Packs", "", "| Pack | Type | Package | Legacy Alias |", "|---|---|---|---|"]
    for skill in load_skill_catalog(repo_root):
        packs = ", ".join(skill.packs) if skill.packs else "unassigned"
        legacy = skill.legacy_name or "n/a"
        pack_lines.append(f"| `{packs}` | `skill` | `{skill.name}` | `{legacy}` |")
    for workflow in load_workflow_catalog(repo_root):
        packs = ", ".join(workflow.packs) if workflow.packs else "unassigned"
        pack_lines.append(f"| `{packs}` | `workflow` | `{workflow.package}` | `n/a` |")
    packs_md.write_text("\n".join(pack_lines) + "\n", encoding="utf-8")

    workflow_catalog = repo_root / "_localsetup" / "docs" / "_generated" / "workflow-catalog.json"
    workflow_catalog.write_text(json.dumps(workflow_catalog_payload(repo_root), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    file_map_md = repo_root / "_localsetup" / "docs" / "_generated" / "implementation-file-map.md"
    map_lines = ["# Implementation File Map", "", "| Classification | Path |", "|---|---|"]
    for entry in implementation_file_map(repo_root):
        map_lines.append(f"| `{entry['classification']}` | `{entry['path']}` |")
    file_map_md.write_text("\n".join(map_lines) + "\n", encoding="utf-8")

    return {
        "aliases": str(aliases_path),
        "migration": str(migration_md),
        "platforms": str(platforms_md),
        "packs": str(packs_md),
        "workflow_catalog": str(workflow_catalog),
        "file_map": str(file_map_md),
        "count": len(aliases),
    }
