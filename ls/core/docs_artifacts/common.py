from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ls.core.provenance import base_provenance, json_with_provenance, markdown_with_provenance


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
    "ls/skills",
    "ls/config/pack.yaml",
    "ls/config/plugin-packs.yaml",
    "ls/workflows",
    "ls/config/platforms.yaml",
    "ls/docs/PLATFORM_REGISTRY.md",
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

        match = VERSION_RE.match(line)
        if match:
            version = match.group(1).strip()

        i += 1

    return {
        "name": name or "",
        "description": desc or "",
        "version": version or "",
    }


def write_markdown(path: Path, text: str, repo_root: Path, *, emitter: str = "generate-docs") -> None:
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


def write_json(path: Path, payload: dict[str, Any], repo_root: Path, *, emitter: str = "generate-docs") -> None:
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
