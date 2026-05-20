from __future__ import annotations

import json
from pathlib import Path

from .aliases import collect_skill_aliases
from .baseline import implementation_file_map
from .manifests import load_platforms
from .provenance import artifact_registry_entry, base_provenance, json_with_provenance, markdown_with_provenance
from .skills import load_skill_catalog, skill_taxonomy_payload
from .workflows import load_workflow_catalog, workflow_catalog_payload


ARTIFACT_SOURCE_INPUTS = [
    "VERSION",
    "_localsetup/skills",
    "_localsetup/config/pack.yaml",
    "_localsetup/workflows",
    "_localsetup/config/platforms.yaml",
    "_localsetup/docs/PLATFORM_REGISTRY.md",
]


def _write_markdown(path: Path, text: str, repo_root: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path = path.relative_to(repo_root) if path.is_absolute() and path.is_relative_to(repo_root) else path
    path.write_text(
        markdown_with_provenance(
            text,
            base_provenance(
                repo_root,
                emitter="generate-docs",
                artifact_path=artifact_path,
                generated_commit_parent=True,
            ),
        ),
        encoding="utf-8",
    )


def _write_json(path: Path, payload: dict, repo_root: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path = path.relative_to(repo_root) if path.is_absolute() and path.is_relative_to(repo_root) else path
    output = json_with_provenance(
        payload,
        base_provenance(
            repo_root,
            emitter="generate-docs",
            artifact_path=artifact_path,
            generated_commit_parent=True,
        ),
    )
    path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_artifact_registry(repo_root: Path, paths: list[Path]) -> None:
    registry_path = repo_root / "_localsetup" / "docs" / "_generated" / "artifact-registry.json"
    existing = {}
    if registry_path.exists():
        try:
            payload = json.loads(registry_path.read_text(encoding="utf-8"))
            existing = {
                str(item.get("path")): item
                for item in payload.get("artifacts", [])
                if item.get("path") and (repo_root / str(item.get("path"))).exists()
            }
        except json.JSONDecodeError:
            existing = {}
    for path in sorted({p.resolve() for p in paths if p.exists()}, key=lambda p: p.as_posix()):
        artifact_type = "json" if path.suffix == ".json" else "markdown" if path.suffix == ".md" else path.suffix.lstrip(".")
        entry = artifact_registry_entry(
            repo_root,
                path,
            artifact_type=artifact_type,
            emitter="generate-docs",
            source_inputs=ARTIFACT_SOURCE_INPUTS,
            generated_commit_parent=True,
        )
        existing[str(entry["path"])] = entry
    _write_json(registry_path, {"schema_version": 1, "artifacts": [existing[key] for key in sorted(existing)]}, repo_root)


def generate_alias_outputs(repo_root: Path) -> dict:
    aliases = collect_skill_aliases(repo_root / "_localsetup" / "skills")
    aliases_path = repo_root / "_localsetup" / "docs" / "_generated" / "skill_aliases.json"
    _write_json(aliases_path, aliases, repo_root)

    migration_md = repo_root / "_localsetup" / "docs" / "migration" / "skill-alias-map.md"
    version_file = repo_root / "VERSION"
    version = version_file.read_text(encoding="utf-8").strip() if version_file.exists() else "3.0.0"
    major_minor = ".".join(version.split(".")[:2]) if "." in version else version
    lines = [
        "---",
        "status: ACTIVE",
        f"version: {major_minor}",
        "owner_package: generate-docs",
        "---",
        "",
        "# Skill Alias Map",
        "",
        "| Previous names | Current names |",
        "|---|---|",
    ]
    for old, new in sorted(aliases.items()):
        lines.append(f"| `{old}` | `{new}` |")
    _write_markdown(migration_md, "\n".join(lines) + "\n", repo_root)

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
    _write_markdown(platforms_md, "\n".join(platform_lines) + "\n", repo_root)

    packs_md = repo_root / "_localsetup" / "docs" / "_generated" / "skill-packs.md"
    pack_lines = [
        "# Skill And Workflow Packs",
        "",
        "| Pack | Type | Package | Class | Priority | Tags | Legacy Alias |",
        "|---|---|---|---|---:|---|---|",
    ]
    for skill in load_skill_catalog(repo_root):
        packs = ", ".join(skill.packs) if skill.packs else "unassigned"
        legacy = skill.legacy_name or "n/a"
        tags = ", ".join(skill.tags) if skill.tags else "n/a"
        pack_lines.append(
            f"| `{packs}` | `skill` | `{skill.name}` | `{skill.taxonomy_class}` | {skill.sort_priority} | `{tags}` | `{legacy}` |"
        )
    for workflow in load_workflow_catalog(repo_root):
        packs = ", ".join(workflow.packs) if workflow.packs else "unassigned"
        pack_lines.append(f"| `{packs}` | `workflow` | `{workflow.package}` | n/a | n/a | n/a | `n/a` |")
    _write_markdown(packs_md, "\n".join(pack_lines) + "\n", repo_root)

    workflow_catalog = repo_root / "_localsetup" / "docs" / "_generated" / "workflow-catalog.json"
    _write_json(workflow_catalog, workflow_catalog_payload(repo_root), repo_root)

    skill_taxonomy = repo_root / "_localsetup" / "docs" / "_generated" / "skill-taxonomy.json"
    _write_json(skill_taxonomy, skill_taxonomy_payload(repo_root), repo_root)

    file_map_md = repo_root / "_localsetup" / "docs" / "_generated" / "implementation-file-map.md"
    map_lines = ["# Implementation File Map", "", "| Classification | Path |", "|---|---|"]
    for entry in implementation_file_map(repo_root):
        map_lines.append(f"| `{entry['classification']}` | `{entry['path']}` |")
    _write_markdown(file_map_md, "\n".join(map_lines) + "\n", repo_root)
    _write_artifact_registry(repo_root, [aliases_path, migration_md, platforms_md, packs_md, workflow_catalog, skill_taxonomy, file_map_md])

    return {
        "aliases": str(aliases_path),
        "migration": str(migration_md),
        "platforms": str(platforms_md),
        "packs": str(packs_md),
        "workflow_catalog": str(workflow_catalog),
        "skill_taxonomy": str(skill_taxonomy),
        "file_map": str(file_map_md),
        "count": len(aliases),
    }
