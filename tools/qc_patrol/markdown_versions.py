from __future__ import annotations

from pathlib import Path
from typing import Any

from .drift import make_packet
from .redaction import redact_text


IGNORED_PATH_PARTS = (
    "CHANGELOG",
    "changelog",
    "migration",
    "MIGRATION",
    "archive",
    "ARCHIVE",
    "/audits/",
    "ls/skills/",
    "_generated",
)
IGNORED_LINE_WORDS = ("example", "sample", "provenance", "historical", "migrate", "migration", "changelog", "released")
LOCALSETUP_VERSION_WORDS = ("localsetup", "framework version", "repo version", "release version", "`version`", " version ")


def _line_context(lines: list[str], line_no: int) -> str:
    start = max(0, line_no - 2)
    end = min(len(lines), line_no + 1)
    return "\n".join(lines[start:end])


def _is_ignored_context(path: str, line: str) -> bool:
    if any(part in path for part in IGNORED_PATH_PARTS):
        return True
    lower = line.lower()
    return any(word in lower for word in IGNORED_LINE_WORDS)


def _looks_like_localsetup_version_claim(line: str) -> bool:
    lower = f" {line.lower()} "
    return any(word in lower for word in LOCALSETUP_VERSION_WORDS)


def markdown_version_packets(repo: Path, inventory: dict[str, Any]) -> dict[str, Any]:
    truth_version = str((inventory.get("version_truth") or {}).get("value", ""))
    packets: list[dict[str, Any]] = []
    references = (inventory.get("surfaces") or {}).get("version_references", [])
    for ref in references if isinstance(references, list) else []:
        path = str(ref.get("path", ""))
        value = str(ref.get("value", ""))
        line_no = int(ref.get("line", 0) or 0)
        doc_class = str(ref.get("doc_class", ""))
        if not path or not value or value == truth_version or doc_class not in {"public", "framework"}:
            continue
        full = repo / path
        if not full.exists() or line_no < 1:
            continue
        lines = full.read_text(encoding="utf-8", errors="replace").splitlines()
        line = lines[line_no - 1] if line_no <= len(lines) else ""
        if _is_ignored_context(path, line) or not _looks_like_localsetup_version_claim(line):
            continue
        snippet = redact_text(_line_context(lines, line_no))
        packets.append(
            make_packet(
                kind="markdown.version_reference_drift",
                reason="Current-facing markdown contains a version reference that differs from VERSION.",
                severity_hint="medium",
                affected_paths=[path],
                facts={"found_version": value, "current_version": truth_version, "line": line_no, "doc_class": doc_class},
                deterministic_evidence=[{"path": path, "line": line_no, "value": value, "current_version": truth_version}],
                snippets=[{"path": path, "line": line_no, "text": snippet}],
                question="Is this version reference intentionally historical, or should it track the current Localsetup version?",
                redaction_applied=snippet != _line_context(lines, line_no),
            )
        )
    return {"schema_version": "qc.drift-packets.v1", "packets": packets}
