"""Manifest and file discovery helpers for markdown reference audits."""

from __future__ import annotations

import glob
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from markdown_reference_config import _normalize_path, _sanitize_text

@dataclass(frozen=True)
class ManifestNote:
    kind: str
    path: Path
    detail: str = ""

def _collect_glob_files(
    base_dir: Path, patterns: list[str], excludes: list[str]
) -> set[Path]:
    found: set[Path] = set()
    for pattern in patterns:
        full = (
            str((base_dir / pattern).resolve())
            if not Path(pattern).is_absolute()
            else pattern
        )
        for match in glob.glob(full, recursive=True):
            p = Path(match)
            if not p.is_file():
                continue
            if any(
                p.match(ex) or str(p).startswith(str((base_dir / ex).resolve()))
                for ex in excludes
            ):
                continue
            found.add(p.resolve())
    return found

def _strip_jsonc(text: str) -> str:
    out: list[str] = []
    in_string = False
    escape = False
    line_comment = False
    block_comment = False
    i = 0

    while i < len(text):
        char = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""

        if line_comment:
            if char in "\r\n":
                line_comment = False
                out.append(char)
            i += 1
            continue

        if block_comment:
            if char == "*" and nxt == "/":
                block_comment = False
                i += 2
            else:
                if char in "\r\n":
                    out.append(char)
                i += 1
            continue

        if in_string:
            out.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            i += 1
            continue

        if char == '"':
            in_string = True
            out.append(char)
            i += 1
            continue
        if char == "/" and nxt == "/":
            line_comment = True
            i += 2
            continue
        if char == "/" and nxt == "*":
            block_comment = True
            i += 2
            continue

        out.append(char)
        i += 1

    return "".join(out)

def _strip_trailing_json_commas(text: str) -> str:
    out: list[str] = []
    in_string = False
    escape = False
    i = 0

    while i < len(text):
        char = text[i]
        if in_string:
            out.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            i += 1
            continue

        if char == '"':
            in_string = True
            out.append(char)
            i += 1
            continue

        if char == ",":
            j = i + 1
            while j < len(text) and text[j].isspace():
                j += 1
            if j < len(text) and text[j] in "}]":
                i += 1
                continue

        out.append(char)
        i += 1

    return "".join(out)

def _load_json_or_jsonc(path: Path) -> Any:
    raw = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".jsonc":
        raw = _strip_trailing_json_commas(_strip_jsonc(raw))
    return json.loads(raw)

def _discover_manifest_targets(
    manifest_path: Path, repo_root: Path
) -> tuple[set[Path], list[ManifestNote]]:
    discovered: set[Path] = set()
    notes: list[ManifestNote] = []

    if not manifest_path.is_file():
        notes.append(ManifestNote("manifest-missing", manifest_path))
        return discovered, notes

    try:
        data = _load_json_or_jsonc(manifest_path)
    except json.JSONDecodeError as exc:
        notes.append(ManifestNote("manifest-invalid-json-or-jsonc", manifest_path, str(exc)))
        return discovered, notes
    except OSError as exc:
        notes.append(ManifestNote("manifest-read-error", manifest_path, str(exc)))
        return discovered, notes

    if not isinstance(data, dict):
        notes.append(ManifestNote("manifest-invalid-schema", manifest_path, "root must be object"))
        return discovered, notes

    instructions = data.get("instructions", [])
    if isinstance(instructions, list):
        for item in instructions:
            text = _sanitize_text(item)
            if not text:
                continue
            if "*" in text:
                discovered |= _collect_glob_files(repo_root, [text], [])
            else:
                p = _normalize_path(text, cwd=manifest_path.parent, repo_root=repo_root)
                if p.is_file() and p.suffix.lower() in {".md", ".mdc"}:
                    discovered.add(p)

    skills = data.get("skills", {}) if isinstance(data.get("skills"), dict) else {}
    paths = skills.get("paths", []) if isinstance(skills.get("paths"), list) else []
    for item in paths:
        text = _sanitize_text(item)
        if not text:
            continue
        p = _normalize_path(text, cwd=manifest_path.parent, repo_root=repo_root)
        if p.is_dir():
            discovered |= _collect_glob_files(
                p, ["**/SKILL.md"], ["**/node_modules/**"]
            )

    notes.append(ManifestNote("manifest-ok", manifest_path))
    return discovered, notes
