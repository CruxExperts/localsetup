#!/usr/bin/env python3
# Purpose: Generate public doc artifacts from canonical framework sources.
# Created: 2026-02-19
# Last updated: 2026-02-19

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
import sys


_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from _localsetup.v3.provenance import artifact_registry_entry, base_provenance, json_with_provenance, markdown_with_provenance
from _localsetup.v3.docs import generate_alias_outputs
from _localsetup.v3.skills import load_skill_catalog, skill_taxonomy_payload
from _localsetup.v3.workflows import load_workflow_catalog, workflow_catalog_payload

from docs_alignment import generate_alignment_artifacts


FRONTMATTER_BOUNDARY = re.compile(r"^---\s*$", re.MULTILINE)
VERSION_RE = re.compile(r'^\s*version:\s*["\']?([0-9.]+)["\']?\s*$')

ASCII_REPLACEMENTS = {
    "–": "-",
    "—": "-",
    "…": "...",
    "’": "'",
    "“": '"',
    "”": '"',
}

ARTIFACT_SOURCE_INPUTS = [
    "VERSION",
    "_localsetup/skills",
    "_localsetup/config/pack.yaml",
    "_localsetup/workflows",
    "_localsetup/config/platforms.yaml",
    "_localsetup/docs/PLATFORM_REGISTRY.md",
]


def ascii_clean(value: str) -> str:
    for old, new in ASCII_REPLACEMENTS.items():
        value = value.replace(old, new)
    return value


def read_frontmatter(md_path: Path) -> dict[str, str]:
    text = md_path.read_text(encoding="utf-8")
    parts = FRONTMATTER_BOUNDARY.split(text, maxsplit=2)
    if len(parts) < 3:
        return {}
    block = parts[1].splitlines()

    name = ""
    desc = ""
    version = ""

    i = 0
    while i < len(block):
        line = block[i]
        stripped = line.strip()

        if stripped.startswith("name:"):
            name = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            i += 1
            continue

        if stripped.startswith("description:"):
            raw = stripped.split(":", 1)[1].strip()
            if raw in {"|", ">", "|-", ">-"}:
                desc_lines = []
                i += 1
                while i < len(block):
                    cont = block[i]
                    if cont.startswith("  ") or cont.startswith("\t"):
                        desc_lines.append(cont.strip())
                        i += 1
                        continue
                    if not cont.strip():
                        desc_lines.append("")
                        i += 1
                        continue
                    break
                desc = " ".join([s for s in desc_lines if s]).strip()
                continue
            desc = raw.strip().strip('"').strip("'")
            i += 1
            continue

        m = VERSION_RE.match(line)
        if m:
            version = m.group(1).strip()

        i += 1

    return {
        "name": name or "",
        "description": desc or "",
        "version": version or "",
    }


def collect_skills(repo_root: Path) -> list[dict[str, object]]:
    skills = []
    for skill in load_skill_catalog(repo_root):
        skill_md = skill.path / "SKILL.md"
        name = skill.name
        description = ascii_clean(skill.description.replace("\n", " ").strip())
        skills.append(
            {
                "id": skill.name,
                "name": name,
                "description": description,
                "version": skill.version,
                "path": str(skill_md.relative_to(repo_root)),
                "class": skill.taxonomy_class,
                "sort_priority": skill.sort_priority,
                "tags": skill.tags,
                "owner_scope": skill.owner_scope,
                "packs": skill.packs,
            }
        )
    return skills


def collect_workflows(repo_root: Path) -> list[dict[str, object]]:
    workflows = []
    for workflow in load_workflow_catalog(repo_root):
        workflows.append(
            {
                "id": workflow.workflow_id,
                "package": workflow.package,
                "name": workflow.display_name,
                "description": ascii_clean(workflow.description.replace("\n", " ").strip()),
                "aliases": workflow.aliases,
                "required_skills": workflow.required_skills,
                "required_tools": workflow.required_tools,
                "required_docs": workflow.required_docs,
                "packs": workflow.packs,
                "path": str((workflow.path / "SKILL.md").relative_to(repo_root)),
            }
        )
    return workflows


def collect_platforms(platform_registry: Path) -> list[dict[str, str]]:
    rows = []
    in_supported_platforms = False
    for line in platform_registry.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("##"):
            in_supported_platforms = stripped.startswith("## Supported platforms")
            continue
        if not in_supported_platforms:
            continue
        if not line.startswith("|"):
            continue
        if stripped.startswith("| ID ") or stripped.startswith("|----"):
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) != 4:
            continue
        platform_id, display, context_loader, skills_path = parts
        if not platform_id:
            continue
        rows.append(
            {
                "id": platform_id,
                "display_name": display,
                "context_loader": context_loader,
                "skills_path": skills_path,
            }
        )
    return rows


def _write_markdown(path: Path, text: str, repo_root: Path, *, emitter: str = "generate-docs") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path = path.relative_to(repo_root) if path.is_absolute() and path.is_relative_to(repo_root) else path
    path.write_text(
        markdown_with_provenance(
            text,
            base_provenance(
                repo_root,
                emitter=emitter,
                artifact_path=artifact_path,
                generated_commit_parent=True,
            ),
        ),
        encoding="utf-8",
    )


def _write_json(path: Path, payload: dict, repo_root: Path, *, emitter: str = "generate-docs") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path = path.relative_to(repo_root) if path.is_absolute() and path.is_relative_to(repo_root) else path
    output = json_with_provenance(
        payload,
        base_provenance(
            repo_root,
            emitter=emitter,
            artifact_path=artifact_path,
            generated_commit_parent=True,
        ),
    )
    path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_artifact_registry(repo_root: Path, paths: list[Path]) -> None:
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
        rel = path.relative_to(repo_root).as_posix()
        artifact_type = "json" if path.suffix == ".json" else "markdown" if path.suffix == ".md" else path.suffix.lstrip(".")
        existing[rel] = artifact_registry_entry(
            repo_root,
            path,
            artifact_type=artifact_type,
            emitter="generate-docs",
            source_inputs=ARTIFACT_SOURCE_INPUTS,
            generated_commit_parent=True,
        )
    _write_json(
        registry_path,
        {"schema_version": 1, "artifacts": [existing[key] for key in sorted(existing)]},
        repo_root,
        emitter="generate-docs",
    )


def write_skills_md(path: Path, major_minor: str, skills: list[dict[str, object]], repo_root: Path) -> None:
    lines = [
        "---",
        "status: ACTIVE",
        f"version: {major_minor}",
        "owner_package: generate-docs",
        "---",
        "",
        "# Shipped skills catalog",
        "",
        "This page is generated from `_localsetup/skills/*/SKILL.md`.",
        "",
        f"Total shipped skills: {len(skills)}",
        "",
        "| Skill ID | Class | Priority | Packs | Tags | Name | Version | Description |",
        "|---|---|---:|---|---|---|---|---|",
    ]

    for skill in skills:
        desc = str(skill["description"] or "").replace("|", "\\|")
        if not desc:
            desc = "No description in frontmatter."
        packs = ", ".join(f"`{pack}`" for pack in skill["packs"]) if skill["packs"] else "unassigned"
        tags = ", ".join(f"`{tag}`" for tag in skill["tags"]) if skill["tags"] else "n/a"
        lines.append(
            f"| `{skill['id']}` | `{skill['class']}` | {skill['sort_priority']} | {packs} | {tags} | `{skill['name']}` | `{skill['version'] or 'n/a'}` | {desc} |"
        )

    lines.append("")

    _write_markdown(path, "\n".join(lines), repo_root)


def write_workflow_registry(path: Path, major_minor: str, workflows: list[dict[str, object]], repo_root: Path) -> None:
    def doc_link(doc: str) -> str:
        if doc.startswith("_localsetup/docs/"):
            target = doc.removeprefix("_localsetup/docs/")
        else:
            target = f"../../{doc}"
        return f"[{Path(doc).name}]({target})"

    lines = [
        "---",
        "status: ACTIVE",
        f"version: {major_minor}",
        "owner_package: generate-docs",
        "---",
        "",
        "# Workflow and module registry (Localsetup v3)",
        "",
        "This page is generated from `_localsetup/workflows/*/workflow.yaml`.",
        "",
        "For the framework rules, see [WORKFLOW_STANDARD.md](WORKFLOW_STANDARD.md).",
        "",
        "## Core",
        "",
        "| Name | Description | When to use | Impact review |",
        "|------|-------------|-------------|---------------|",
        "| Master rule / context | Always-loaded framework context | Always | No |",
        "| Skills index | List of capability skills and when to use | When discovering which skill to load | No |",
        "",
        "## Workflows",
        "",
        "| Workflow ID | Package | Name | Description | Aliases | Required skills | Primary docs/tools |",
        "|-------------|---------|------|-------------|---------|-----------------|--------------------|",
    ]
    for workflow in workflows:
        aliases = "; ".join(workflow["aliases"]) if workflow["aliases"] else "n/a"
        required_skills = "; ".join(f"`{name}`" for name in workflow["required_skills"]) or "n/a"
        docs = "; ".join(doc_link(str(doc)) for doc in workflow["required_docs"])
        tools = "; ".join(f"`{tool}`" for tool in workflow["required_tools"])
        primary = "; ".join(part for part in [docs, tools] if part) or "n/a"
        description = str(workflow["description"]).replace("|", "\\|") or "No description in frontmatter."
        lines.append(
            f"| `{workflow['id']}` | `{workflow['package']}` | {workflow['name']} | {description} | {aliases} | {required_skills} | {primary} |"
        )

    lines.extend(
        [
            "",
            "## Usage",
            "",
            "- Agents load the workflow package when a user invokes a workflow ID, package name, or alias.",
            "- Workflow packages install into the managed skill library because every package includes a valid `SKILL.md`.",
            "- Required skills listed in `workflow.yaml` are automatically selected when a workflow's pack is selected.",
            "- Historical publish workflow pointers are retired; use `ls-github-publishing-workflow` plus `ls-automatic-versioning`.",
            "",
        ]
    )
    _write_markdown(path, "\n".join(lines), repo_root)


def write_workflow_quick_ref(path: Path, major_minor: str, workflows: list[dict[str, object]], repo_root: Path) -> None:
    lines = [
        "---",
        "status: ACTIVE",
        f"version: {major_minor}",
        "owner_package: generate-docs",
        "---",
        "",
        "# Workflow quick reference",
        "",
        "This page is generated from `_localsetup/workflows/*/workflow.yaml`.",
        "",
        "## Workflows",
        "",
        "| Workflow ID | Name | Aliases | Package | Required skills |",
        "|------------|------|---------|---------|-----------------|",
    ]
    for workflow in workflows:
        aliases = "; ".join(workflow["aliases"]) if workflow["aliases"] else "n/a"
        required_skills = "; ".join(f"`{name}`" for name in workflow["required_skills"]) or "n/a"
        lines.append(
            f"| `{workflow['id']}` | {workflow['name']} | {aliases} | `{workflow['package']}` | {required_skills} |"
        )
    lines.extend(
        [
            "",
            "## Common Phrases",
            "",
        ]
    )
    for workflow in workflows:
        for alias in workflow["aliases"]:
            lines.append(f"- \"{alias}\" -> `{workflow['id']}`")
    lines.append("")
    _write_markdown(path, "\n".join(lines), repo_root)


def write_facts_json(path: Path, facts: dict, repo_root: Path) -> None:
    output = {k: v for k, v in facts.items() if k != "generated_at"}
    _write_json(path, output, repo_root)


def write_workflow_catalog_json(path: Path, repo_root: Path) -> None:
    _write_json(path, workflow_catalog_payload(repo_root), repo_root)


def write_skill_taxonomy_json(path: Path, repo_root: Path) -> None:
    _write_json(path, skill_taxonomy_payload(repo_root), repo_root)


def write_internal_snapshot(path: Path, facts: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Internal docs snapshot",
        "",
        "Local-only generated report. Do not commit.",
        "",
        f"- generated_at: {facts['generated_at']}",
        f"- version: {facts['version']}",
        f"- platform_count: {facts['platform_count']}",
        f"- skill_count: {facts['skill_count']}",
        f"- workflow_count: {facts['workflow_count']}",
        "",
        "## Platforms",
    ]
    for p in facts["platforms"]:
        lines.append(f"- {p['id']}: {p['display_name']}")
    lines.append("")
    lines.append("## Skills")
    for skill in facts["skills"]:
        lines.append(f"- {skill['id']}")
    lines.append("")
    lines.append("## Workflows")
    for workflow in facts["workflows"]:
        lines.append(f"- {workflow['id']}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def replace_managed_block(path: Path, marker: str, content: str) -> None:
    start = f"<!-- {marker}:start -->"
    end = f"<!-- {marker}:end -->"
    text = path.read_text(encoding="utf-8")
    if start not in text or end not in text:
        return
    pre, rest = text.split(start, 1)
    _, post = rest.split(end, 1)
    new_text = f"{pre}{start}\n{content}\n{end}{post}"
    path.write_text(new_text, encoding="utf-8")


def update_facts_blocks(repo_root: Path, facts: dict) -> None:
    platforms = ", ".join([p["id"] for p in facts["platforms"]])

    readme_block = "\n".join(
        [
            "| Fact | Value |",
            "|---|---|",
            f"| Current version | `{facts['version']}` |",
            f"| Supported platforms | `{platforms}` |",
            f"| Shipped skills | `{facts['skill_count']}` |",
            f"| Workflow packages | `{facts['workflow_count']}` |",
            "| Source | `_localsetup/docs/_generated/facts.json` |",
        ]
    )
    docs_index_block = "\n".join(
        [
            f"- Current version: `{facts['version']}`",
            f"- Supported platforms: `{platforms}`",
            f"- Shipped skills: `{facts['skill_count']}`",
            f"- Workflow packages: `{facts['workflow_count']}`",
            "- Source: `_localsetup/docs/_generated/facts.json`",
        ]
    )

    replace_managed_block(repo_root / "README.md", "facts-block", readme_block)
    replace_managed_block(
        repo_root / "_localsetup" / "docs" / "README.md",
        "facts-block",
        docs_index_block,
    )
    replace_managed_block(
        repo_root / "_localsetup" / "docs" / "FEATURES.md",
        "facts-block",
        docs_index_block,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Localsetup documentation artifacts."
    )
    parser.add_argument("--repo-root", default=None, help="Repository root path.")
    parser.add_argument(
        "--internal-output",
        default="",
        help="Optional path for local-only internal snapshot report. Disabled by default.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = (
        Path(args.repo_root).resolve()
        if args.repo_root
        else Path(__file__).resolve().parents[2]
    )

    version = (repo_root / "VERSION").read_text(encoding="utf-8").strip()
    major_minor = ".".join(version.split(".")[:2]) if "." in version else version

    docs_dir = repo_root / "_localsetup" / "docs"
    platform_registry = docs_dir / "PLATFORM_REGISTRY.md"

    skills = collect_skills(repo_root)
    workflows = collect_workflows(repo_root)
    platforms = collect_platforms(platform_registry)

    facts = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "version": version,
        "major_minor": major_minor,
        "platform_count": len(platforms),
        "skill_count": len(skills),
        "workflow_count": len(workflows),
        "platforms": platforms,
        "skills": [
            {
                "id": s["id"],
                "name": s["name"],
                "version": s["version"],
                "path": s["path"],
                "class": s["class"],
                "sort_priority": s["sort_priority"],
                "tags": s["tags"],
                "owner_scope": s["owner_scope"],
                "packs": s["packs"],
            }
            for s in skills
        ],
        "workflows": [
            {
                "id": str(w["id"]),
                "package": str(w["package"]),
                "name": str(w["name"]),
                "path": str(w["path"]),
            }
            for w in workflows
        ],
    }

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
    write_workflow_catalog_json(docs_dir / "_generated" / "workflow-catalog.json", repo_root)
    write_skill_taxonomy_json(docs_dir / "_generated" / "skill-taxonomy.json", repo_root)
    alias_outputs = generate_alias_outputs(repo_root)
    alignment_outputs = generate_alignment_artifacts(repo_root)
    if args.internal_output:
        write_internal_snapshot(repo_root / args.internal_output, facts)
    update_facts_blocks(repo_root, facts)
    alias_output_paths = [Path(output) for key, output in alias_outputs.items() if key != "count"]
    write_artifact_registry(
        repo_root,
        [*direct_outputs, *alias_output_paths, *(Path(output) for output in alignment_outputs.values())],
    )

    print("Generated: _localsetup/docs/SKILLS.md")
    print("Generated: _localsetup/docs/WORKFLOW_REGISTRY.md")
    print("Generated: _localsetup/docs/WORKFLOW_QUICK_REF.md")
    print("Generated: _localsetup/docs/_generated/facts.json")
    print("Generated: _localsetup/docs/_generated/workflow-catalog.json")
    print("Generated: _localsetup/docs/_generated/skill-taxonomy.json")
    for output in alignment_outputs.values():
        print(f"Generated: {Path(output).relative_to(repo_root)}")
    print("Generated: _localsetup/docs/_generated/artifact-registry.json")
    if args.internal_output:
        print(f"Generated: {args.internal_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
