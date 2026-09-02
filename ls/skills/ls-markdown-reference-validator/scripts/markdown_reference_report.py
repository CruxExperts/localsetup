"""Report rendering and target collection for markdown reference audits."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from markdown_reference_config import (
    Config,
    Finding,
    _display_path,
    _normalize_path,
    _sanitize_text,
)
from markdown_reference_discovery import ManifestNote, _collect_glob_files, _discover_manifest_targets


def _display_target(target: str, *, repo_root: Path) -> str:
    target_path = Path(target)
    if not target_path.is_absolute():
        return target
    return _display_path(target_path, repo_root=repo_root)


def _display_finding_detail(finding: Finding, *, repo_root: Path) -> str:
    detail = finding.detail
    for raw, display in (
        (finding.source_file, _display_path(Path(finding.source_file), repo_root=repo_root)),
        (finding.target, _display_target(finding.target, repo_root=repo_root)),
        (finding.resolved_path, _display_path(Path(finding.resolved_path), repo_root=repo_root)),
    ):
        if raw:
            detail = detail.replace(raw, display)
    return detail

def _display_manifest_note(note: ManifestNote, *, repo_root: Path) -> str:
    safe_path = _display_path(note.path, repo_root=repo_root)
    safe_detail = note.detail.replace(str(note.path), safe_path)
    suffix = f" ({safe_detail})" if safe_detail else ""
    return f"{note.kind}:{safe_path}{suffix}"
def _render_report(
    *,
    config_path: Path,
    config: Config,
    reason: str,
    files_scanned: list[Path],
    checked_refs: int,
    findings: list[Finding],
    manifest_notes: list[ManifestNote],
) -> str:
    ts = datetime.now().astimezone().isoformat(timespec="seconds")

    missing_paths = sum(1 for f in findings if f.category == "missing_path")
    missing_anchors = sum(1 for f in findings if f.category == "missing_anchor")
    read_issues = sum(1 for f in findings if f.category.startswith("unreadable_"))

    lines: list[str] = [
        "# Markdown Reference Audit",
        "",
        f"Updated: {ts}",
        "Status: ACTIVE",
        f"Source: {_display_path(config_path, repo_root=config.repo_root)}",
        f"Auto reason: {reason}",
        "",
        "## Summary",
        "",
        f"- Files scanned: **{len(files_scanned)}**",
        f"- Local references checked: **{checked_refs}**",
        f"- Findings: **{len(findings)}**",
        f"- Missing paths: **{missing_paths}**",
        f"- Missing anchors: **{missing_anchors}**",
        f"- Read issues: **{read_issues}**",
        "",
        "## Config",
        "",
        f"- Repo root: {_display_path(config.repo_root, repo_root=config.repo_root)}",
        f"- Report path: {_display_path(config.report_path, repo_root=config.repo_root)}",
        f"- State file: {_display_path(config.state_file, repo_root=config.repo_root)}",
        f"- Max findings: `{config.max_findings}`",
        f"- Inline code mode: `{config.inline_code_mode}`",
        f"- Ignore source globs: `{len(config.ignore.source_file_globs)}`",
        f"- Ignore target regexes: `{len(config.ignore.target_regexes)}`",
        f"- Ignore path prefixes: `{len(config.ignore.path_prefixes)}`",
        f"- Placeholder tokens: `{len(config.ignore.placeholder_tokens)}`",
        "",
        "## Kilo manifest discovery notes",
        "",
    ]

    if manifest_notes:
        for note in manifest_notes:
            lines.append(f"- {_display_manifest_note(note, repo_root=config.repo_root)}")
    else:
        lines.append("- None")

    lines.extend(["", "## Findings", ""])

    if findings:
        lines.extend(
            [
                "| Category | Source | Line | Target | Resolved path | Detail |",
                "|----------|--------|------|--------|---------------|--------|",
            ]
        )
        for f in findings:
            source = _display_path(Path(f.source_file), repo_root=config.repo_root)
            resolved = _display_path(Path(f.resolved_path), repo_root=config.repo_root)
            target = _display_target(f.target, repo_root=config.repo_root)
            detail = _display_finding_detail(f, repo_root=config.repo_root)
            lines.append(
                f"| {f.category} | {source} | {f.line} | {target} | {resolved} | {detail} |"
            )
    else:
        lines.append("- No missing local references detected.")

    lines.extend(
        [
            "",
            "## Recommended next steps",
            "",
            "1. Fix missing path findings by updating target paths or creating intended files.",
            "2. Fix missing anchor findings by correcting `#anchor` fragments to match markdown headings.",
            "3. Re-run the audit (`--force`) after updates to confirm a clean result.",
            "",
        ]
    )
    return "\n".join(lines)

def _collect_files(
    config: Config, config_path: Path
) -> tuple[list[Path], list[ManifestNote]]:
    files: set[Path] = set()
    manifest_notes: list[ManifestNote] = []

    for target in config.targets:
        if not isinstance(target, dict):
            continue
        base_dir_raw = _sanitize_text(
            target.get("base_dir", "{repo_root}"), fallback="{repo_root}"
        )
        base_dir = _normalize_path(
            base_dir_raw, cwd=config_path.parent, repo_root=config.repo_root
        )
        include = target.get("include_globs", [])
        exclude = target.get("exclude_globs", [])

        include_list = (
            [_sanitize_text(x) for x in include if _sanitize_text(x)]
            if isinstance(include, list)
            else []
        )
        exclude_list = (
            [_sanitize_text(x) for x in exclude if _sanitize_text(x)]
            if isinstance(exclude, list)
            else []
        )
        if not include_list:
            continue

        files |= _collect_glob_files(base_dir, include_list, exclude_list)

    for manifest in config.kilo_manifests:
        manifest_path = _normalize_path(
            manifest, cwd=config_path.parent, repo_root=config.repo_root
        )
        discovered, notes = _discover_manifest_targets(manifest_path, config.repo_root)
        files |= discovered
        manifest_notes.extend(notes)

    sorted_files = sorted(files)
    return sorted_files, manifest_notes
