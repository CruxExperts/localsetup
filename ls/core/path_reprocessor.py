from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any


TEXT_SUFFIXES = {
    ".md",
    ".py",
    ".sh",
    ".yaml",
    ".yml",
    ".json",
    ".toml",
    ".txt",
    ".cfg",
    ".ini",
}
TEXT_FILENAMES = {"install", "VERSION", "LICENSE", "MANIFEST.in", "AGENTS.md", "README.md"}
EXCLUDED_PREFIXES = (
    ".git/",
    ".codex/",
    ".agents/state/",
    ".localsetup-maint/",
    ".localsetup/",
    "graphify-out/",
    "state/",
    "data/",
    "__pycache__/",
    "dist/",
    "build/",
)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _tracked_files(repo_root: Path) -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return sorted(
            path.relative_to(repo_root)
            for path in repo_root.rglob("*")
            if path.is_file() and ".git" not in path.relative_to(repo_root).parts
        )
    return [Path(line) for line in completed.stdout.splitlines() if line.strip()]


def _is_text_candidate(rel: Path) -> bool:
    rel_text = rel.as_posix()
    if any(rel_text == prefix.rstrip("/") or rel_text.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
        return False
    return rel.suffix in TEXT_SUFFIXES or rel.name in TEXT_FILENAMES


def _rewrite_source_text(text: str) -> tuple[str, list[dict[str, str]]]:
    actions: list[dict[str, str]] = []
    replacements = {
        "ls/docs/": "localsetup://doc/",
        "./ls/docs/": "localsetup://doc/",
        "../../docs/": "localsetup://doc/",
        "ls/tools/": "localsetup://tool/",
        "./ls/tools/": "localsetup://tool/",
    }
    rewritten = text
    for before, after in replacements.items():
        if before in rewritten:
            rewritten = rewritten.replace(before, after)
            actions.append({"from": before, "to": after})
    return rewritten, actions


def reprocess_localsetup_paths(repo_root: Path, *, apply: bool = False) -> dict[str, Any]:
    root = repo_root.expanduser().resolve(strict=False)
    files: list[dict[str, Any]] = []
    for rel in _tracked_files(root):
        if not _is_text_candidate(rel):
            continue
        path = root / rel
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        before_hash = _sha256_text(text)
        rewritten, actions = _rewrite_source_text(text)
        after_hash = _sha256_text(rewritten)
        changed = before_hash != after_hash
        if changed and apply:
            path.write_text(rewritten, encoding="utf-8")
        files.append(
            {
                "path": rel.as_posix(),
                "pre_hash": before_hash,
                "post_hash": after_hash,
                "changed": changed,
                "actions": actions,
            }
        )
    changed_files = [item for item in files if item["changed"]]
    return {
        "ok": True,
        "mode": "apply" if apply else "report-only",
        "files_scanned": len(files),
        "changed_files": len(changed_files),
        "files": files,
    }
