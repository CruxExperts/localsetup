"""Version file synchronization helpers."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

from .docs import generate_alias_outputs
from .versioning_constants import VERSIONED_DOC_EXCLUDED_PARTS, VERSIONED_DOC_GLOBS, VERSION_SYNC_PREFIX
from .versioning_models import SemVer

GitText = Callable[[Path, list[str]], str]
RunGit = Callable[[Path, list[str]], subprocess.CompletedProcess[str]]
SyncVersionFiles = Callable[[Path, str], dict]
ResolveHead = Callable[[Path], str]
StageVersionFiles = Callable[[Path], None]


def replace_regex(path: Path, pattern: str, replacement: str, *, flags: int = re.MULTILINE) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    new_text = re.sub(pattern, replacement, text, flags=flags)
    if new_text == text:
        return False
    path.write_text(new_text, encoding="utf-8")
    return True


def update_doc_frontmatter_versions(
    repo_root: Path,
    version: SemVer,
    *,
    include_path: Callable[[str], bool] | None = None,
) -> list[str]:
    changed: list[str] = []
    for pattern in VERSIONED_DOC_GLOBS:
        for path in sorted(repo_root.glob(pattern)):
            relative_path = path.relative_to(repo_root).as_posix()
            if include_path is not None and not include_path(relative_path):
                continue
            if any(part in VERSIONED_DOC_EXCLUDED_PARTS for part in path.relative_to(repo_root).parts):
                continue
            text = path.read_text(encoding="utf-8")
            if not text.startswith("---\n"):
                continue
            parts = text.split("---", 2)
            if len(parts) < 3:
                continue
            frontmatter = parts[1]
            new_frontmatter = re.sub(
                r'(?m)^version:\s*["\']?[0-9]+(?:\.[0-9]+){1,2}["\']?\s*$',
                f"version: {version.major_minor}",
                frontmatter,
            )
            if not new_frontmatter.endswith("\n"):
                new_frontmatter = f"{new_frontmatter}\n"
            new_text = f"---{new_frontmatter}---{parts[2]}"
            if new_text != text:
                path.write_text(new_text, encoding="utf-8")
                changed.append(str(path.relative_to(repo_root)))
    return changed


def sync_version_files(repo_root: Path, target_version: str) -> dict:
    target = SemVer.parse(target_version)
    changed: list[str] = []
    tracked_updates = [
        ("VERSION", lambda path: path.write_text(f"{target}\n", encoding="utf-8")),
    ]
    for rel_path, writer in tracked_updates:
        path = repo_root / rel_path
        before = path.read_text(encoding="utf-8") if path.exists() else None
        writer(path)
        after = path.read_text(encoding="utf-8")
        if before != after:
            changed.append(rel_path)

    replacements = [
        ("pyproject.toml", r'(?m)^version = "[0-9]+\.[0-9]+\.[0-9]+"$', f'version = "{target}"'),
        ("README.md", r"(?m)^\*\*Version:\*\* [0-9]+\.[0-9]+\.[0-9]+<br>$", f"**Version:** {target}<br>"),
        ("ls/README.md", r"(?m)^\*\*Version:\*\* [0-9]+\.[0-9]+\.[0-9]+<br>$", f"**Version:** {target}<br>"),
        (
            "ls/docs/VERSIONING.md",
            r"(?m)^- Current value: `[0-9]+\.[0-9]+\.[0-9]+`$",
            f"- Current value: `{target}`",
        ),
        (
            "uv.lock",
            r'(?m)(^\[\[package\]\]\nname = "localsetup"\nversion = ")[0-9]+\.[0-9]+\.[0-9]+(")',
            rf"\g<1>{target}\2",
        ),
    ]
    for rel_path, pattern, replacement in replacements:
        if replace_regex(repo_root / rel_path, pattern, replacement):
            changed.append(rel_path)

    changed.extend(update_doc_frontmatter_versions(repo_root, target))
    generator = repo_root / "ls" / "tools" / "generate_docs_artifacts.py"
    subprocess.run(
        [sys.executable, str(generator), "--repo-root", str(repo_root)],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=True,
    )
    generate_alias_outputs(repo_root)

    generated_paths = [
        "README.md",
        "ls/docs/README.md",
        "ls/docs/FEATURES.md",
        "ls/docs/SKILLS.md",
        "ls/docs/WORKFLOW_REGISTRY.md",
        "ls/docs/WORKFLOW_QUICK_REF.md",
        "ls/docs/_generated/facts.json",
        "ls/docs/_generated/workflow-catalog.json",
        "ls/docs/_generated/skill-taxonomy.json",
        "ls/docs/_generated/plugin-packs.json",
        "ls/docs/_generated/plugin-packs.md",
        "ls/docs/_generated/docs-inventory.json",
        "ls/docs/_generated/docs-truth-map.json",
        "ls/docs/_generated/docs-audit-result.json",
        "ls/docs/_generated/docs-asset-manifest.json",
        "ls/docs/_generated/docs-alignment-summary.md",
        "ls/docs/_generated/artifact-registry.json",
        "assets/README.md",
        "ls/docs/migration/skill-alias-map.md",
        "ls/docs/_generated/platform-adapters.md",
        "ls/docs/_generated/skill-packs.md",
        "ls/docs/_generated/skill_aliases.json",
        "ls/docs/_generated/implementation-file-map.md",
    ]
    for rel_path in generated_paths:
        if rel_path not in changed:
            changed.append(rel_path)

    return {
        "version": str(target),
        "major_minor": target.major_minor,
        "changed_candidates": sorted(set(changed)),
    }


def check_version_files(
    repo_root: Path,
    target_version: str,
    *,
    git_text: GitText,
    run_git: RunGit,
    sync: SyncVersionFiles,
) -> dict:
    candidates = {
        repo_root / "VERSION",
        repo_root / "pyproject.toml",
        repo_root / "uv.lock",
        repo_root / "README.md",
        repo_root / "ls" / "README.md",
        repo_root / "ls" / "docs" / "VERSIONING.md",
        repo_root / "ls" / "docs" / "README.md",
        repo_root / "ls" / "docs" / "FEATURES.md",
        repo_root / "ls" / "docs" / "SKILLS.md",
        repo_root / "ls" / "docs" / "WORKFLOW_REGISTRY.md",
        repo_root / "ls" / "docs" / "WORKFLOW_QUICK_REF.md",
        repo_root / "ls" / "docs" / "_generated" / "facts.json",
        repo_root / "ls" / "docs" / "_generated" / "workflow-catalog.json",
        repo_root / "ls" / "docs" / "_generated" / "skill-taxonomy.json",
        repo_root / "ls" / "docs" / "_generated" / "plugin-packs.json",
        repo_root / "ls" / "docs" / "_generated" / "plugin-packs.md",
        repo_root / "ls" / "docs" / "_generated" / "docs-inventory.json",
        repo_root / "ls" / "docs" / "_generated" / "docs-truth-map.json",
        repo_root / "ls" / "docs" / "_generated" / "docs-audit-result.json",
        repo_root / "ls" / "docs" / "_generated" / "docs-asset-manifest.json",
        repo_root / "ls" / "docs" / "_generated" / "docs-alignment-summary.md",
        repo_root / "ls" / "docs" / "_generated" / "artifact-registry.json",
        repo_root / "assets" / "README.md",
        repo_root / "ls" / "docs" / "_generated" / "implementation-file-map.md",
        repo_root / "ls" / "docs" / "_generated" / "platform-adapters.md",
        repo_root / "ls" / "docs" / "_generated" / "skill-packs.md",
        repo_root / "ls" / "docs" / "_generated" / "skill_aliases.json",
        repo_root / "ls" / "docs" / "migration" / "skill-alias-map.md",
    }
    candidates.update(
        path
        for path in (repo_root / "ls" / "docs").glob("**/*.md")
        if not any(part in VERSIONED_DOC_EXCLUDED_PARTS for part in path.relative_to(repo_root).parts)
    )
    before_contents = {
        path: path.read_text(encoding="utf-8") if path.exists() else None
        for path in candidates
    }
    before = git_text(repo_root, ["status", "--porcelain"])
    before_diff = run_git(repo_root, ["diff", "--name-only"], check=False).stdout.splitlines()
    before_staged = run_git(repo_root, ["diff", "--cached", "--name-only"], check=False).stdout.splitlines()
    sync(repo_root, target_version)
    after = git_text(repo_root, ["status", "--porcelain"])
    diff = run_git(repo_root, ["diff", "--name-only"], check=False).stdout.splitlines()
    staged = run_git(repo_root, ["diff", "--cached", "--name-only"], check=False).stdout.splitlines()
    ok = before == after and diff == before_diff and staged == before_staged
    for path, content in before_contents.items():
        if content is None:
            if path.exists():
                path.unlink()
            continue
        path.write_text(content, encoding="utf-8")
    return {
        "ok": ok,
        "dirty_before": before,
        "dirty_after": after,
        "diff_before": before_diff,
        "diff_after": diff,
        "staged_before": before_staged,
        "staged_after": staged,
    }


def stage_version_files(repo_root: Path, *, run_git: RunGit) -> None:
    fixed_paths = [
        "VERSION",
        "pyproject.toml",
        "uv.lock",
        "README.md",
        "ls/README.md",
        "ls/docs/VERSIONING.md",
        "ls/docs/_generated/facts.json",
        "ls/docs/_generated/workflow-catalog.json",
        "ls/docs/_generated/skill-taxonomy.json",
        "ls/docs/_generated/plugin-packs.json",
        "ls/docs/_generated/plugin-packs.md",
        "ls/docs/_generated/docs-inventory.json",
        "ls/docs/_generated/docs-truth-map.json",
        "ls/docs/_generated/docs-audit-result.json",
        "ls/docs/_generated/docs-asset-manifest.json",
        "ls/docs/_generated/docs-alignment-summary.md",
        "ls/docs/_generated/artifact-registry.json",
        "ls/docs/_generated/implementation-file-map.md",
        "ls/docs/_generated/platform-adapters.md",
        "ls/docs/_generated/skill-packs.md",
        "ls/docs/_generated/skill_aliases.json",
        "ls/docs/migration/skill-alias-map.md",
        "ls/docs/SKILLS.md",
        "assets/README.md",
    ]
    doc_paths = [
        str(path.relative_to(repo_root))
        for path in (repo_root / "ls" / "docs").glob("**/*.md")
        if not any(part in VERSIONED_DOC_EXCLUDED_PARTS for part in path.relative_to(repo_root).parts)
    ]
    paths = sorted(set(fixed_paths + doc_paths))
    run_git(repo_root, ["add", *paths])


def commit_version_sync(
    repo_root: Path,
    target_version: str,
    *,
    git_text: GitText,
    run_git: RunGit,
    resolve_head: ResolveHead,
    stage: StageVersionFiles,
) -> str | None:
    stage(repo_root)
    staged = git_text(repo_root, ["diff", "--cached", "--name-only"])
    if not staged:
        return None
    run_git(repo_root, ["commit", "-m", f"{VERSION_SYNC_PREFIX} {target_version}"])
    return resolve_head(repo_root)


def commit_generated_docs_refresh(
    repo_root: Path,
    *,
    git_text: GitText,
    run_git: RunGit,
    resolve_head: ResolveHead,
    stage: StageVersionFiles,
    message: str = "docs: refresh generated artifacts",
) -> str | None:
    stage(repo_root)
    staged = git_text(repo_root, ["diff", "--cached", "--name-only"])
    if not staged:
        return None
    run_git(repo_root, ["commit", "-m", message, "-m", "Release-Type: none"])
    return resolve_head(repo_root)
