from __future__ import annotations

from pathlib import Path


DEFAULT_SCAN_SUFFIXES = {".md", ".yaml", ".yml", ".json", ".toml", ".txt", ".sh", ".py", ".ps1"}
SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules"}


def scan_legacy_references(repo_root: Path, needle: str = "localsetup-") -> list[dict]:
    findings: list[dict] = []
    for path in sorted(repo_root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in DEFAULT_SCAN_SUFFIXES:
            continue
        rel = path.relative_to(repo_root)
        if rel.parts[:2] == ("_localsetup", "skills"):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_no, line in enumerate(lines, start=1):
            if needle in line:
                findings.append({"path": str(rel), "line": line_no, "text": line.strip()[:240]})
    return findings
