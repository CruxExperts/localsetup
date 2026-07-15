from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ls.core.client_registry import load_client_registry, projection_matches

from .collectors import collect_platforms, collect_skills, collect_workflows
from .writers import (
    generate_alias_output_paths,
    update_facts_blocks,
    write_artifact_registry,
    write_facts_json,
    write_internal_snapshot,
    write_skill_taxonomy_json,
    write_skills_md,
    write_workflow_catalog_json,
    write_workflow_quick_ref,
    write_workflow_registry,
)


AlignmentGenerator = Callable[[Path], dict[str, str]]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Localsetup documentation artifacts.")
    parser.add_argument("--repo-root", default=None, help="Repository root path.")
    parser.add_argument(
        "--internal-output",
        default="",
        help="Optional path for local-only internal snapshot report. Disabled by default.",
    )
    return parser.parse_args(argv)


def _facts(repo_root: Path, major_minor: str, skills: list[dict[str, Any]], workflows: list[dict[str, Any]], platforms: list[dict[str, str]]) -> dict[str, Any]:
    version = (repo_root / "VERSION").read_text(encoding="utf-8").strip()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "version": version,
        "major_minor": major_minor,
        "platform_count": len(platforms),
        "skill_count": len(skills),
        "workflow_count": len(workflows),
        "platforms": platforms,
        "skills": [
            {
                "id": skill["id"],
                "name": skill["name"],
                "version": skill["version"],
                "path": skill["path"],
                "class": skill["class"],
                "sort_priority": skill["sort_priority"],
                "tags": skill["tags"],
                "owner_scope": skill["owner_scope"],
                "packs": skill["packs"],
            }
            for skill in skills
        ],
        "workflows": [
            {
                "id": str(workflow["id"]),
                "package": str(workflow["package"]),
                "name": str(workflow["name"]),
                "path": str(workflow["path"]),
            }
            for workflow in workflows
        ],
    }


def run(repo_root: Path, internal_output: str, alignment_generator: AlignmentGenerator) -> None:
    version = (repo_root / "VERSION").read_text(encoding="utf-8").strip()
    major_minor = ".".join(version.split(".")[:2]) if "." in version else version
    docs_dir = repo_root / "ls" / "docs"

    skills = collect_skills(repo_root)
    workflows = collect_workflows(repo_root)
    registry = load_client_registry(repo_root)
    if not projection_matches(repo_root, registry):
        raise RuntimeError(
            "ls/config/platforms.yaml is stale; run `localsetup client-registry generate` before generating docs"
        )
    platforms = collect_platforms(repo_root)
    facts = _facts(repo_root, major_minor, skills, workflows, platforms)

    direct_outputs = [
        docs_dir / "SKILLS.md",
        docs_dir / "WORKFLOW_REGISTRY.md",
        docs_dir / "WORKFLOW_QUICK_REF.md",
        docs_dir / "_generated" / "facts.json",
        docs_dir / "_generated" / "workflow-catalog.json",
        docs_dir / "_generated" / "skill-taxonomy.json",
    ]
    write_skills_md(direct_outputs[0], major_minor, skills, repo_root)
    write_workflow_registry(direct_outputs[1], major_minor, workflows, repo_root)
    write_workflow_quick_ref(direct_outputs[2], major_minor, workflows, repo_root)
    write_facts_json(direct_outputs[3], facts, repo_root)
    write_workflow_catalog_json(direct_outputs[4], repo_root)
    write_skill_taxonomy_json(direct_outputs[5], repo_root)

    alias_output_paths = generate_alias_output_paths(repo_root)
    alignment_outputs = alignment_generator(repo_root)
    if internal_output:
        write_internal_snapshot(repo_root / internal_output, facts)
    update_facts_blocks(repo_root, facts)
    write_artifact_registry(
        repo_root,
        [*direct_outputs, *alias_output_paths, *(Path(output) for output in alignment_outputs.values())],
    )

    for rel_path in (
        "ls/docs/SKILLS.md",
        "ls/docs/WORKFLOW_REGISTRY.md",
        "ls/docs/WORKFLOW_QUICK_REF.md",
        "ls/docs/_generated/facts.json",
        "ls/docs/_generated/workflow-catalog.json",
        "ls/docs/_generated/skill-taxonomy.json",
        "ls/docs/_generated/plugin-packs.json",
        "ls/docs/_generated/plugin-packs.md",
    ):
        print(f"Generated: {rel_path}")
    for output in alignment_outputs.values():
        print(f"Generated: {Path(output).relative_to(repo_root)}")
    print("Generated: ls/docs/_generated/artifact-registry.json")
    if internal_output:
        print(f"Generated: {internal_output}")


def main(argv: list[str] | None = None, *, alignment_generator: AlignmentGenerator) -> int:
    args = parse_args(argv)
    repo_root = Path(args.repo_root).resolve() if args.repo_root else Path(__file__).resolve().parents[3]
    run(repo_root, args.internal_output, alignment_generator)
    return 0
