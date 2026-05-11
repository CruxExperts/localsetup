from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import yaml

from .manifests import load_pack_config
from .paths import PathValidationError, repo_path
from .skills import parse_skill_frontmatter, selected_pack_names


WORKFLOW_PACKAGE_PREFIX = "ls-workflow-"
WORKFLOW_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
REQUIRED_WORKFLOW_KEYS = {
    "workflow_id",
    "display_name",
    "aliases",
    "invocation",
    "required_skills",
    "required_tools",
    "required_docs",
    "gates",
    "phases",
    "validation",
    "outputs",
    "smoke",
    "migration",
}


@dataclass(frozen=True)
class WorkflowInfo:
    package: str
    workflow_id: str
    display_name: str
    description: str
    aliases: list[str]
    path: Path
    required_skills: list[str]
    required_tools: list[str]
    required_docs: list[str]
    gates: list[dict[str, Any]]
    phases: list[dict[str, Any]]
    validation: list[dict[str, Any]]
    outputs: list[str]
    smoke: list[dict[str, Any]]
    migration: dict[str, Any]
    packs: list[str]


def workflow_package_name(workflow_id: str) -> str:
    return f"{WORKFLOW_PACKAGE_PREFIX}{workflow_id}"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"missing workflow manifest: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"workflow manifest is not a mapping: {path}")
    return data


def _str_list(data: dict[str, Any], field: str) -> list[str]:
    value = data.get(field, [])
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"{field} must be a list of non-empty strings")
    return [item.strip() for item in value]


def _mapping_list(data: dict[str, Any], field: str) -> list[dict[str, Any]]:
    value = data.get(field, [])
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{field} must be a list of mappings")
    return value


def _reverse_workflow_packs(repo_root: Path) -> dict[str, list[str]]:
    pack = load_pack_config(repo_root)
    reverse: dict[str, list[str]] = {}
    for pack_name, workflow_names in pack.workflow_packs.items():
        for workflow_name in workflow_names:
            reverse.setdefault(workflow_name, []).append(pack_name)
    return reverse


def load_workflow_catalog(repo_root: Path) -> list[WorkflowInfo]:
    workflows_root = repo_root / "_localsetup" / "workflows"
    if not workflows_root.exists():
        return []

    reverse_packs = _reverse_workflow_packs(repo_root)
    catalog: list[WorkflowInfo] = []
    for workflow_dir in sorted(workflows_root.glob(f"{WORKFLOW_PACKAGE_PREFIX}*")):
        if not workflow_dir.is_dir():
            continue
        manifest_path = workflow_dir / "workflow.yaml"
        skill_md = workflow_dir / "SKILL.md"
        try:
            manifest = _load_yaml(manifest_path)
        except ValueError:
            manifest = {}
        frontmatter = parse_skill_frontmatter(skill_md) if skill_md.is_file() else {}
        workflow_id = str(manifest.get("workflow_id", "")).strip()
        display_name = str(manifest.get("display_name", "")).strip()
        package = workflow_dir.name
        catalog.append(
            WorkflowInfo(
                package=package,
                workflow_id=workflow_id,
                display_name=display_name,
                description=str(frontmatter.get("description", "")).strip(),
                aliases=_str_list(manifest, "aliases"),
                path=workflow_dir,
                required_skills=_str_list(manifest, "required_skills"),
                required_tools=_str_list(manifest, "required_tools"),
                required_docs=_str_list(manifest, "required_docs"),
                gates=_mapping_list(manifest, "gates"),
                phases=_mapping_list(manifest, "phases"),
                validation=_mapping_list(manifest, "validation"),
                outputs=_str_list(manifest, "outputs"),
                smoke=_mapping_list(manifest, "smoke"),
                migration=manifest.get("migration") if isinstance(manifest.get("migration"), dict) else {},
                packs=sorted(reverse_packs.get(package, [])),
            )
        )
    return catalog


def selected_workflow_names(repo_root: Path, requested_packs: list[str] | None) -> list[str]:
    pack = load_pack_config(repo_root)
    names = selected_pack_names(repo_root, requested_packs)
    selected: list[str] = []
    for pack_name in names:
        selected.extend(pack.workflow_packs.get(pack_name, []))
    return sorted(set(selected))


def required_skills_for_workflows(repo_root: Path, workflow_names: list[str]) -> list[str]:
    by_package = {workflow.package: workflow for workflow in load_workflow_catalog(repo_root)}
    required: set[str] = set()
    for workflow_name in workflow_names:
        workflow = by_package.get(workflow_name)
        if workflow:
            required.update(workflow.required_skills)
    return sorted(required)


def workflow_catalog_payload(repo_root: Path) -> dict[str, Any]:
    workflows = []
    for workflow in load_workflow_catalog(repo_root):
        workflows.append(
            {
                "package": workflow.package,
                "workflow_id": workflow.workflow_id,
                "display_name": workflow.display_name,
                "description": workflow.description,
                "aliases": workflow.aliases,
                "required_skills": workflow.required_skills,
                "required_tools": workflow.required_tools,
                "required_docs": workflow.required_docs,
                "packs": workflow.packs,
                "path": str(workflow.path.relative_to(repo_root)),
            }
        )
    return {"workflows": workflows, "count": len(workflows)}


def validate_workflow_catalog(repo_root: Path) -> list[str]:
    issues: list[str] = []
    pack = load_pack_config(repo_root)
    workflows_root = repo_root / "_localsetup" / "workflows"
    skills_root = repo_root / "_localsetup" / "skills"
    skill_names = {path.name for path in skills_root.glob("ls-*") if path.is_dir()}

    if not workflows_root.is_dir():
        issues.append("missing workflows source root: _localsetup/workflows")
        return issues

    try:
        workflows = load_workflow_catalog(repo_root)
    except ValueError as exc:
        issues.append(str(exc))
        return issues
    package_names = {workflow.package for workflow in workflows}
    all_workflow_ids = {workflow.workflow_id for workflow in workflows if workflow.workflow_id}
    workflow_ids: dict[str, str] = {}
    aliases: dict[str, str] = {}

    for pack_name, workflow_names in pack.workflow_packs.items():
        if pack_name not in pack.packs:
            issues.append(f"workflow pack references unknown pack: {pack_name}")
        for workflow_name in workflow_names:
            if workflow_name not in package_names:
                issues.append(f"pack references missing workflow: {pack_name}:{workflow_name}")

    for workflow in workflows:
        skill_md = workflow.path / "SKILL.md"
        manifest_path = workflow.path / "workflow.yaml"
        frontmatter = parse_skill_frontmatter(skill_md) if skill_md.is_file() else {}
        frontmatter_name = str(frontmatter.get("name", "")).strip()
        try:
            manifest = _load_yaml(manifest_path)
        except ValueError as exc:
            issues.append(str(exc))
            manifest = {}
        missing_keys = sorted(REQUIRED_WORKFLOW_KEYS - set(manifest))
        if missing_keys:
            issues.append(f"workflow manifest missing keys: {manifest_path}:{', '.join(missing_keys)}")

        if not skill_md.is_file():
            issues.append(f"missing workflow SKILL.md: {workflow.path}")
        if not manifest_path.is_file():
            issues.append(f"missing workflow.yaml: {workflow.path}")
        if not workflow.package.startswith(WORKFLOW_PACKAGE_PREFIX):
            issues.append(f"workflow package missing {WORKFLOW_PACKAGE_PREFIX} prefix: {workflow.path}")
        if not workflow.workflow_id:
            issues.append(f"missing workflow_id: {manifest_path}")
        elif not WORKFLOW_ID_RE.fullmatch(workflow.workflow_id):
            issues.append(f"invalid workflow_id: {manifest_path}:{workflow.workflow_id}")
        elif workflow.package != workflow_package_name(workflow.workflow_id):
            issues.append(f"workflow package/id mismatch: {workflow.path}")
        if workflow.workflow_id in workflow_ids:
            issues.append(f"duplicate workflow_id: {workflow.workflow_id}")
        elif workflow.workflow_id:
            workflow_ids[workflow.workflow_id] = workflow.package

        if not frontmatter_name:
            issues.append(f"missing workflow SKILL.md frontmatter name: {skill_md}")
        elif frontmatter_name != workflow.package:
            issues.append(f"workflow SKILL.md name mismatch: {skill_md}")
        if not workflow.description:
            issues.append(f"missing workflow SKILL.md description: {skill_md}")
        if not workflow.display_name:
            issues.append(f"missing display_name: {manifest_path}")
        if not workflow.smoke:
            issues.append(f"workflow missing smoke row: {manifest_path}")
        if not workflow.packs:
            issues.append(f"workflow not assigned to a pack: {workflow.package}")

        reserved = set(skill_names) | all_workflow_ids | package_names
        for alias in workflow.aliases:
            normalized = alias.strip().lower()
            if normalized in reserved:
                issues.append(f"workflow alias conflicts with reserved name: {workflow.package}:{alias}")
            if normalized in aliases:
                issues.append(f"workflow alias collision: {alias} ({aliases[normalized]} and {workflow.package})")
            aliases[normalized] = workflow.package

        for skill_name in workflow.required_skills:
            if skill_name not in skill_names:
                issues.append(f"workflow requires missing skill: {workflow.package}:{skill_name}")
        for tool in workflow.required_tools:
            if "/" in tool or "\\" in tool or tool.startswith((".", "~", "_localsetup")):
                try:
                    tool_path = repo_path(repo_root, tool, f"workflow required_tools {workflow.package}")
                except PathValidationError as exc:
                    issues.append(f"workflow requires unsafe tool path: {workflow.package}:{tool}: {exc}")
                    continue
                if not tool_path.exists():
                    issues.append(f"workflow requires missing tool: {workflow.package}:{tool}")
        for doc in workflow.required_docs:
            try:
                doc_path = repo_path(repo_root, doc, f"workflow required_docs {workflow.package}")
            except PathValidationError as exc:
                issues.append(f"workflow requires unsafe doc path: {workflow.package}:{doc}: {exc}")
                continue
            if not doc_path.is_file():
                issues.append(f"workflow requires missing doc: {workflow.package}:{doc}")

    return issues
