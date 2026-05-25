from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .aliases import legacy_skill_name, skill_alias
from .manifests import load_pack_config
from .schema import validate_json_schema

ALLOWED_SKILL_TAXONOMY_CLASSES = {
    "core",
    "framework-governance",
    "development",
    "operations",
    "integrations",
    "skill-lifecycle",
    "specialized",
}


@dataclass(frozen=True)
class SkillInfo:
    name: str
    legacy_name: str | None
    path: Path
    description: str
    version: str
    packs: list[str]
    taxonomy_class: str
    sort_priority: int
    tags: list[str]
    owner_scope: str


def parse_skill_frontmatter(skill_md: Path) -> dict:
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}
    data = yaml.safe_load(text[4:end])
    return data if isinstance(data, dict) else {}


def _candidate_skill_dir(candidate: Path) -> Path:
    path = candidate.expanduser().resolve()
    return path.parent if path.name == "SKILL.md" else path


def _path_under(path: Path, base: Path) -> bool:
    try:
        resolved_path = path.resolve()
        resolved_base = base.expanduser().resolve()
        return resolved_path == resolved_base or resolved_base in resolved_path.parents
    except (OSError, RuntimeError):
        return False


def _candidate_managed_path_findings(repo_root: Path, skill_dir: Path, home: Path | None) -> tuple[list[str], list[str]]:
    blockers: list[str] = []
    warnings: list[str] = []
    managed_roots = [repo_root / "_localsetup" / "skills"]
    if home is None:
        home = Path.home()
    if home is not None:
        managed_roots.extend(
            [
                home / ".local" / "share" / "localsetup" / "source",
                home / ".local" / "share" / "localsetup" / "packages",
            ]
        )
    for root in managed_roots:
        if _path_under(skill_dir, root):
            blockers.append(f"candidate path is inside managed Localsetup content: {root}")
    adapter_roots = [
        ".agents/skills",
        ".codex/skills",
        ".claude/skills",
        ".cursor/skills",
        ".kilo/skills",
        ".openclaw/skills",
        ".opencode/skills",
    ]
    for rel in adapter_roots:
        root = repo_root / rel
        if _path_under(skill_dir, root):
            blockers.append(f"candidate path is inside an adapter skill directory: {rel}")
    expected_root = repo_root / "docs" / "localsetup" / "skills"
    if not _path_under(skill_dir, expected_root):
        warnings.append("candidate is outside the recommended docs/localsetup/skills/<skill-name>/ contract")
    return blockers, warnings


def candidate_skill_path_blockers(repo_root: Path, path: Path, *, home: Path | None = None) -> list[str]:
    blockers, _warnings = _candidate_managed_path_findings(repo_root, path.expanduser().resolve(), home)
    return blockers


def _candidate_safety_findings(repo_root: Path, skill_dir: Path) -> dict[str, Any]:
    try:
        from _localsetup.tools import skill_validation_scan

        pattern_path = skill_validation_scan.resolve_pattern_file_path(None, repo_root)
        ok, message = skill_validation_scan.ensure_pattern_file(pattern_path, fetch_if_missing=False)
        if not ok:
            return {"ok": False, "message": message, "findings": []}
        patterns = skill_validation_scan.load_patterns(pattern_path)
        hits, non_english = skill_validation_scan.scan_skill_dir(skill_dir, pattern_path, patterns)
        findings = [
            {
                "file": hit["file"],
                "line": hit["line"],
                "col": hit["col"],
                "pattern_id": hit["pattern_id"],
                "description": hit["description"],
            }
            for hit in hits
        ]
        if non_english:
            findings.append(
                {
                    "file": str(skill_dir / "SKILL.md"),
                    "line": None,
                    "col": None,
                    "pattern_id": "possible_non_latin_language_content",
                    "description": "Manual review for possible hidden prompt content.",
                }
            )
        return {"ok": True, "message": "ok", "findings": findings}
    except Exception as exc:
        return {"ok": False, "message": f"{type(exc).__name__}: {exc}", "findings": []}


def validate_candidate_skill(repo_root: Path, candidate: Path, *, home: Path | None = None) -> dict[str, Any]:
    skill_dir = _candidate_skill_dir(candidate)
    skill_md = skill_dir / "SKILL.md"
    blockers, warnings = _candidate_managed_path_findings(repo_root, skill_dir, home)
    if not skill_md.is_file():
        blockers.append("candidate must contain SKILL.md")
        frontmatter: dict[str, Any] = {}
    else:
        try:
            frontmatter = parse_skill_frontmatter(skill_md)
        except yaml.YAMLError as exc:
            blockers.append(f"candidate SKILL.md frontmatter is invalid YAML: {exc.__class__.__name__}")
            frontmatter = {}
    name = str(frontmatter.get("name") or "")
    description = str(frontmatter.get("description") or "")
    if not name:
        blockers.append("candidate SKILL.md frontmatter must include name")
    if name and not name.startswith("ls-"):
        warnings.append("candidate skill name should use the ls- namespace")
    if name and skill_dir.name != name:
        warnings.append("candidate directory name should match frontmatter name")
    if not description:
        blockers.append("candidate SKILL.md frontmatter must include description")
    safety = _candidate_safety_findings(repo_root, skill_dir) if skill_md.is_file() else {"ok": True, "message": "skipped", "findings": []}
    if not safety["ok"]:
        warnings.append(f"content-safety scan unavailable: {safety['message']}")
    return {
        "ok": not blockers,
        "schema_version": 1,
        "candidate": {
            "path": str(skill_dir),
            "skill_md": str(skill_md),
            "name": name,
            "description": description,
        },
        "validation": {
            "blockers": blockers,
            "warnings": warnings,
        },
        "safety": safety,
    }


def candidate_skill_proposal(repo_root: Path, candidate: Path, *, home: Path | None = None) -> dict[str, Any]:
    payload = validate_candidate_skill(repo_root, candidate, home=home)
    candidate_data = payload["candidate"]
    name = candidate_data["name"] or Path(candidate_data["path"]).name
    description = candidate_data["description"] or "(description missing)"
    issue_text = (
        f"Propose repo-scoped Localsetup skill candidate `{name}`.\n\n"
        f"Summary: {description}\n\n"
        "Requested review:\n"
        "- Confirm the skill belongs in Localsetup or should remain downstream.\n"
        "- Review validation blockers, warnings, and content-safety references.\n"
        "- Decide separately whether to promote into `_localsetup/skills/`."
    )
    adapter_preview = {
        "supported": False,
        "reason": "candidate-skill v1 is validation/proposal only and does not mutate adapters",
    }
    return {
        "ok": payload["ok"],
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "candidate": candidate_data,
        "validation": payload["validation"],
        "safety": payload["safety"],
        "suggested_upstream_text": issue_text,
        "adapter_preview": adapter_preview,
    }


def candidate_skill_proposal_markdown(payload: dict[str, Any]) -> str:
    candidate = payload["candidate"]
    validation = payload["validation"]
    safety = payload["safety"]
    lines = [
        "# Candidate skill proposal",
        "",
        f"- Candidate: `{candidate.get('name') or Path(str(candidate.get('path'))).name}`",
        f"- Path: `{candidate.get('path')}`",
        f"- Description: {candidate.get('description') or '(missing)'}",
        f"- Validation: {'ok' if payload.get('ok') else 'blocked'}",
        "",
        "## Validation",
        "",
    ]
    blockers = validation.get("blockers") or []
    warnings = validation.get("warnings") or []
    lines.extend([f"- Blocker: {item}" for item in blockers] or ["- Blocker: none"])
    lines.extend([f"- Warning: {item}" for item in warnings] or ["- Warning: none"])
    lines.extend(["", "## Safety Findings", ""])
    findings = safety.get("findings") or []
    if findings:
        for item in findings:
            location = item.get("file")
            if item.get("line"):
                location = f"{location}:{item.get('line')}:{item.get('col')}"
            lines.append(f"- {item.get('pattern_id')}: {location} - {item.get('description')}")
    else:
        lines.append("- none")
    lines.extend(["", "## Suggested Upstream Text", "", payload["suggested_upstream_text"], ""])
    return "\n".join(lines)


def selected_pack_names(repo_root: Path, requested_packs: list[str] | None) -> list[str]:
    pack = load_pack_config(repo_root)
    names = requested_packs if requested_packs is not None else ["core"]
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


def _taxonomy_row(pack_taxonomy: dict[str, dict[str, Any]], skill_name: str) -> dict[str, Any]:
    row = pack_taxonomy.get(skill_name, {})
    priority = row.get("sort_priority", 1_000_000)
    return {
        "class": str(row.get("class", "")),
        "sort_priority": priority if type(priority) is int else 1_000_000,
        "tags": [str(tag) for tag in row.get("tags", [])] if isinstance(row.get("tags", []), list) else [],
        "owner_scope": str(row.get("owner_scope", "")),
    }


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
        taxonomy = _taxonomy_row(pack.skill_taxonomy, canonical_name)
        catalog.append(
            SkillInfo(
                name=canonical_name,
                legacy_name=legacy_name if legacy_name != canonical_name else None,
                path=skill_dir,
                description=str(frontmatter.get("description", "")),
                version=str(frontmatter.get("metadata", {}).get("version", "") if isinstance(frontmatter.get("metadata", {}), dict) else ""),
                packs=sorted(reverse_packs.get(canonical_name, [])),
                taxonomy_class=taxonomy["class"],
                sort_priority=taxonomy["sort_priority"],
                tags=taxonomy["tags"],
                owner_scope=taxonomy["owner_scope"],
            )
        )
    return sorted(catalog, key=lambda skill: (skill.sort_priority, skill.name))


def skill_taxonomy_payload(repo_root: Path) -> dict[str, Any]:
    skills = load_skill_catalog(repo_root)
    rows = [
        {
            "id": skill.name,
            "class": skill.taxonomy_class,
            "sort_priority": skill.sort_priority,
            "tags": skill.tags,
            "owner_scope": skill.owner_scope,
            "packs": skill.packs,
            "path": str(skill.path.relative_to(repo_root)),
        }
        for skill in skills
    ]
    classes = sorted(
        {
            skill.taxonomy_class
            for skill in skills
            if skill.taxonomy_class
        }
    )
    return {
        "schema_version": 1,
        "count": len(rows),
        "classes": classes,
        "skills": rows,
    }


def validate_skill_catalog(repo_root: Path, *, require_jsonschema: bool = True) -> list[str]:
    issues: list[str] = []
    pack = load_pack_config(repo_root)
    skills_root = repo_root / "_localsetup" / "skills"
    canonical_names = {skill.name for skill in load_skill_catalog(repo_root)}
    taxonomy_names = set(pack.skill_taxonomy)

    for pack_name, skill_names in pack.packs.items():
        for skill_name in skill_names:
            if skill_name.startswith("localsetup-"):
                issues.append(f"pack uses legacy skill name: {pack_name}:{skill_name}")
            if skill_name not in canonical_names:
                issues.append(f"pack references missing skill: {pack_name}:{skill_name}")

    for skill_name in sorted(canonical_names - taxonomy_names):
        issues.append(f"skill missing taxonomy row: {skill_name}")
    for skill_name in sorted(taxonomy_names - canonical_names):
        issues.append(f"taxonomy references missing skill: {skill_name}")

    for skill in load_skill_catalog(repo_root):
        taxonomy = pack.skill_taxonomy.get(skill.name, {})
        taxonomy_class = taxonomy.get("class")
        sort_priority = taxonomy.get("sort_priority")
        tags = taxonomy.get("tags")
        owner_scope = taxonomy.get("owner_scope")
        if taxonomy_class not in ALLOWED_SKILL_TAXONOMY_CLASSES:
            issues.append(f"skill taxonomy class invalid: {skill.name}:{taxonomy_class}")
        if type(sort_priority) is not int or sort_priority < 0:
            issues.append(f"skill taxonomy sort_priority invalid: {skill.name}:{sort_priority}")
        if not isinstance(tags, list) or not all(isinstance(tag, str) and tag.strip() for tag in tags):
            issues.append(f"skill taxonomy tags invalid: {skill.name}")
        if not isinstance(owner_scope, str) or not owner_scope.strip():
            issues.append(f"skill taxonomy owner_scope invalid: {skill.name}")
        frontmatter = parse_skill_frontmatter(skill.path / "SKILL.md")
        issues.extend(
            validate_json_schema(
                frontmatter,
                repo_root / "_localsetup" / "config" / "skill-frontmatter.schema.json",
                label=f"{skill.path.relative_to(repo_root)}/SKILL.md frontmatter",
                required=require_jsonschema,
            )
        )
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
