"""Validate untrusted, in-memory release-documentation proposals.

Only the controller writes accepted content.  This module binds model output to
the exact source material and document bytes that it reviewed.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

from tools.qc_patrol.chunking import chunk_text

from .content import validate_record as validate_content_record
from .schemas import CHUNK_BYTES, MAX_EVIDENCE_ITEMS, MAX_RESPONSE_BYTES


MAX_DOCUMENT_BYTES = 1_000_000
MAX_EDIT_BYTES = 192_000
MAX_TOTAL_EDIT_BYTES = 768_000
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_DISPOSITIONS = {"no_change", "update_recommended", "needs_follow_up"}
_URL = re.compile(r"https?://[^\s)>\]]+")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def require_plan(plan: Mapping[str, Any]) -> None:
    for key in ("source_commit", "target_version", "baseline_tag"):
        if not isinstance(plan.get(key), str) or not plan[key].strip():
            raise ValueError(f"release documentation plan requires {key}")
    if not _SHA.fullmatch(str(plan["source_commit"])):
        raise ValueError("release documentation plan requires a full source_commit SHA")
    if not isinstance(plan.get("changed_paths"), list) or not isinstance(plan.get("documents"), list):
        raise ValueError("release documentation plan requires changed_paths and documents")


def safe_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("source path must be a non-empty relative path")
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or str(pure) in {".", ""}:
        raise ValueError(f"unsafe source path: {value!r}")
    return pure.as_posix()


def safe_repo_path(root: Path, value: str) -> tuple[str, Path]:
    rel = safe_relative_path(value)
    candidate = Path(root) / rel
    try:
        resolved_root = Path(root).resolve(strict=True)
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"proposal path does not resolve: {rel}") from exc
    if candidate.is_symlink() or not resolved.is_relative_to(resolved_root) or not resolved.is_file():
        raise ValueError(f"proposal path is not a regular repository file: {rel}")
    return rel, resolved


def editable_document_path(root: Path, value: str) -> tuple[str, Path]:
    rel, path = safe_repo_path(root, value)
    if path.suffix.lower() != ".md" or rel == "AGENTS.md" or rel.endswith("SKILL.md"):
        raise ValueError(f"proposal path is not an authored public document: {rel}")
    if rel != "README.md" and not rel.startswith("ls/docs/"):
        raise ValueError(f"proposal path is outside public documentation: {rel}")
    if rel.startswith("ls/docs/_generated/") or "/templates/" in rel or rel.startswith("ls/templates/"):
        raise ValueError(f"proposal path is generated or managed: {rel}")
    return rel, path


def auditable_document_path(root: Path, value: str) -> tuple[str, Path]:
    rel, path = safe_repo_path(root, value)
    if path.suffix.lower() != ".md" or rel == "AGENTS.md" or rel.startswith((".agents/", ".ai/", ".codex/", ".github/")):
        raise ValueError(f"proposal path is not a public documentation input: {rel}")
    return rel, path


def plan_documents(root: Path, plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    require_plan(plan)
    documents: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in plan["documents"]:
        raw = item if isinstance(item, str) else item.get("path") if isinstance(item, Mapping) else None
        rel, path = auditable_document_path(root, raw)
        if rel in seen:
            raise ValueError(f"release documentation plan duplicates {rel}")
        content = path.read_text(encoding="utf-8")
        if len(content.encode("utf-8")) > MAX_DOCUMENT_BYTES:
            raise ValueError(f"release documentation document is too large: {rel}")
        try:
            editable_document_path(root, rel)
            editable = True
        except ValueError:
            editable = False
        documents.append({"path": rel, "content": content, "before_sha256": sha256_text(content), "editable": editable})
        seen.add(rel)
    if not documents:
        raise ValueError("release documentation plan has no active public documents")
    return documents


def normalize_source_material(root: Path, plan: Mapping[str, Any]) -> list[dict[str, str]]:
    """Require complete, bounded source diffs for every changed path."""
    raw_material = plan.get("source_material", plan.get("changed_material", []))
    if not isinstance(raw_material, list):
        raise ValueError("release documentation source_material must be a list")
    references = plan.get("reference_material", [])
    if not isinstance(references, list):
        raise ValueError("release documentation reference_material must be a list")
    reference_paths = {item.get("path") for item in references if isinstance(item, Mapping)}
    allowed_references = {"ls/docs/QUICKSTART.md", "ls/docs/ADAPTER_OWNERSHIP.md",
                          f"ls/docs/releases/{plan.get('reference_version', plan['baseline_tag'][1:])}.json"}
    if not reference_paths <= allowed_references:
        raise ValueError("release documentation reference path is not an authoritative operational document")
    raw_material = [*raw_material, *references]
    material: list[dict[str, str]] = []
    supplied: set[str] = set()
    for item in raw_material:
        if not isinstance(item, Mapping) or not isinstance(item.get("path"), str):
            raise ValueError("release documentation source material requires a path")
        rel = safe_relative_path(item["path"])
        body = item.get("diff", item.get("content"))
        if not isinstance(body, str) or not body.strip():
            raise ValueError(f"source material is empty for {rel}")
        if len(body.encode("utf-8")) > MAX_DOCUMENT_BYTES:
            raise ValueError(f"source material is too large for {rel}")
        if rel in supplied:
            raise ValueError(f"duplicate source material for {rel}")
        material.append({"path": rel, "content": body, "sha256": sha256_text(body),
                         "kind": "reference" if rel in reference_paths else "change"})
        supplied.add(rel)
    changed = {safe_relative_path(path) for path in plan["changed_paths"]}
    missing = sorted(changed - supplied)
    if missing:
        raise ValueError("source material is missing changed paths: " + ", ".join(missing))
    return material


def _parse_response(value: str | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise ValueError("release documentation completion did not return a bounded JSON response")
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("release documentation completion returned invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise ValueError("release documentation completion JSON must be an object")
    return decoded


def _evidence(root: Path, values: object, *, source_paths: set[str] | None = None,
              source_commit: str | None = None) -> list[str]:
    if not isinstance(values, list) or not values or len(values) > MAX_EVIDENCE_ITEMS:
        raise ValueError("proposal evidence must be a non-empty bounded list")
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip() or len(value) > 300:
            raise ValueError("proposal evidence must be a short repository path or full commit SHA")
        evidence = value.strip()
        if _SHA.fullmatch(evidence):
            if source_commit is not None and evidence != source_commit:
                raise ValueError("proposal commit evidence must be the planned source_commit")
            normalized.append(evidence)
            continue
        path = safe_relative_path(evidence)
        if source_paths is not None and path not in source_paths:
            raise ValueError(f"proposal evidence is not backed by supplied source material: {path}")
        if source_paths is None:
            safe_repo_path(root, path)
        normalized.append(path)
    return normalized


def validate_audit_response(root: Path, batch: Sequence[Mapping[str, Any]], response: str | Mapping[str, Any],
                            *, source_paths: set[str] | None = None, source_commit: str | None = None) -> dict[str, Any]:
    payload = _parse_response(response)
    if set(payload) != {"coverage", "edits"} or not isinstance(payload["coverage"], list) or not isinstance(payload["edits"], list):
        raise ValueError("release documentation audit response has an invalid shape")
    expected = {(str(item["path"]), int(item["chunk"])) for item in batch}
    observed: set[tuple[str, int]] = set()
    coverage: list[dict[str, Any]] = []
    for row in payload["coverage"]:
        if not isinstance(row, Mapping) or set(row) != {"path", "chunk", "disposition", "evidence"}:
            raise ValueError("release documentation audit coverage has an invalid shape")
        key = (str(row["path"]), row["chunk"])
        if key not in expected or not isinstance(row["chunk"], int) or key in observed:
            raise ValueError("release documentation audit coverage does not match its prompt batch")
        if row["disposition"] not in _DISPOSITIONS:
            raise ValueError("release documentation audit has an unknown disposition")
        coverage.append({"path": key[0], "chunk": key[1], "disposition": row["disposition"],
                         "evidence": _evidence(root, row["evidence"], source_paths=source_paths, source_commit=source_commit)})
        observed.add(key)
    if observed != expected:
        raise ValueError("release documentation audit coverage is incomplete")
    return {"coverage": coverage, "edits": list(payload["edits"])}


def validate_record(root: Path, plan: Mapping[str, Any], value: object, *, source_paths: set[str] | None = None) -> dict[str, Any]:
    """Apply the engine record schema, then bind every claim to supplied source."""
    try:
        record = validate_content_record(value)
    except ValueError as exc:
        raise ValueError(f"release documentation record is invalid: {exc}") from exc
    for key in ("version", "source_commit", "baseline_tag"):
        expected = plan["target_version"] if key == "version" else plan[key]
        if record[key] != expected:
            raise ValueError(f"release documentation record binding mismatch for {key}")
    for highlight in record["highlights"]:
        highlight["evidence"] = _evidence(root, highlight["evidence"], source_paths=set(plan["changed_paths"]) if source_paths is not None else None,
                                            source_commit=plan["source_commit"])
    return record


def validate_edits(root: Path, documents: Sequence[Mapping[str, Any]], values: object,
                   *, source_paths: set[str] | None = None, source_commit: str | None = None) -> list[dict[str, str]]:
    if not isinstance(values, list) or len(values) > len(documents):
        raise ValueError("release documentation proposal has too many edits")
    allowed = {str(item["path"]): item for item in documents if item.get("editable") is True}
    edits: list[dict[str, str]] = []
    seen: set[str] = set()
    total_bytes = 0
    for item in values:
        if not isinstance(item, Mapping) or set(item) != {"path", "content", "evidence"}:
            raise ValueError("release documentation edit has an invalid shape")
        path, content = item.get("path"), item.get("content")
        if not isinstance(path, str) or path not in allowed or path in seen or not isinstance(content, str):
            raise ValueError("release documentation edit targets an unauthorized document")
        size = len(content.encode("utf-8"))
        if not content.strip() or size > MAX_EDIT_BYTES:
            raise ValueError("release documentation edit content is empty or too large")
        original_urls = set(_URL.findall(str(allowed[path]["content"])))
        if not original_urls.issubset(set(_URL.findall(content))) or "[REDACTED" in content:
            raise ValueError("release documentation edit does not preserve existing URLs")
        total_bytes += size
        if total_bytes > MAX_TOTAL_EDIT_BYTES:
            raise ValueError("release documentation proposal output is too large")
        _evidence(root, item["evidence"], source_paths=source_paths, source_commit=source_commit)
        if source_paths is not None and not any(value in source_paths for value in item["evidence"]):
            raise ValueError("release documentation edits must cite at least one source path, not only a commit")
        edits.append({"path": path, "before_sha256": str(allowed[path]["before_sha256"]), "content": content})
        seen.add(path)
    return edits


def _normalized_edits(documents: Sequence[Mapping[str, Any]], values: object) -> list[dict[str, str]]:
    allowed = {str(item["path"]): item for item in documents if item.get("editable") is True}
    if not isinstance(values, list):
        raise ValueError("release documentation proposal edits must be a list")
    normalized: list[dict[str, str]] = []
    total = 0
    for item in values:
        if not isinstance(item, Mapping) or set(item) != {"path", "before_sha256", "content"}:
            raise ValueError("release documentation normalized edit has an invalid shape")
        path, before, content = item.get("path"), item.get("before_sha256"), item.get("content")
        if not isinstance(path, str) or path not in allowed or before != allowed[path]["before_sha256"] or not isinstance(content, str):
            raise ValueError("release documentation edit targets an unauthorized document")
        size = len(content.encode("utf-8"))
        if not content.strip() or size > MAX_EDIT_BYTES:
            raise ValueError("release documentation edit content is empty or too large")
        original_urls = set(_URL.findall(str(allowed[path]["content"])))
        if not original_urls.issubset(set(_URL.findall(content))) or "[REDACTED" in content:
            raise ValueError("release documentation edit does not preserve existing URLs")
        total += size
        if total > MAX_TOTAL_EDIT_BYTES:
            raise ValueError("release documentation proposal output is too large")
        normalized.append({"path": path, "before_sha256": before, "content": content})
    if len({item["path"] for item in normalized}) != len(normalized):
        raise ValueError("release documentation proposal duplicates an edit path")
    return normalized


def _validate_coverage(root: Path, coverage: object, documents: Sequence[Mapping[str, Any]], source_paths: set[str],
                       source_commit: str) -> list[dict[str, Any]]:
    if not isinstance(coverage, list):
        raise ValueError("release documentation proposal coverage must be a list")
    expected = {
        (str(item["path"]), int(chunk["index"]))
        for item in documents
        for chunk in chunk_text(str(item["path"]), str(item["content"]), CHUNK_BYTES)
    }
    seen: set[tuple[str, int]] = set()
    normalized: list[dict[str, Any]] = []
    for item in coverage:
        if not isinstance(item, Mapping) or set(item) != {"path", "chunk", "disposition", "evidence"}:
            raise ValueError("release documentation proposal has invalid coverage")
        key = (item.get("path"), item.get("chunk"))
        if key not in expected or key in seen or item.get("disposition") not in _DISPOSITIONS:
            raise ValueError("release documentation proposal coverage does not match its documents")
        normalized.append({"path": key[0], "chunk": key[1], "disposition": item["disposition"],
                           "evidence": _evidence(root, item["evidence"], source_paths=source_paths,
                                                 source_commit=source_commit)})
        seen.add(key)
    if seen != expected:
        raise ValueError("release documentation proposal lacks full document coverage")
    if any(item["disposition"] == "needs_follow_up" for item in normalized):
        raise ValueError("release documentation audit has unresolved follow-up")
    return normalized


def _record_claims(record: Mapping[str, Any], source_paths: set[str] | None = None) -> list[tuple[str, set[str]]]:
    claims: list[tuple[str, set[str]]] = [("summary", set())]
    claims.extend((f"highlight:{index}", {item for item in highlight["evidence"] if source_paths is None or item in source_paths})
                  for index, highlight in enumerate(record["highlights"]))
    for section in ("compatibility", "update", "verification"):
        claims.extend((f"{section}:{index}", set()) for index, _ in enumerate(record[section]))
    return claims


def validate_proposal(root: Path, plan: Mapping[str, Any], proposal: Mapping[str, Any]) -> dict[str, Any]:
    """Revalidate a candidate immediately before controller-owned application."""
    documents = plan_documents(root, plan)
    source = normalize_source_material(root, plan)
    source_paths = {item["path"] for item in source}
    reference_paths = {item["path"] for item in source if item["kind"] == "reference"}
    if not isinstance(proposal, Mapping) or set(proposal) != {"record", "edits", "coverage", "review", "binding"}:
        raise ValueError("release documentation proposal has an invalid shape")
    binding = proposal["binding"]
    expected_binding = {
        "source_commit": plan["source_commit"], "target_version": plan["target_version"], "baseline_tag": plan["baseline_tag"],
        "document_sha256": {item["path"]: item["before_sha256"] for item in documents},
        "source_material_sha256": {item["path"]: item["sha256"] for item in source},
        "source_material_kind": {item["path"]: item["kind"] for item in source},
    }
    if not isinstance(binding, Mapping) or any(binding.get(key) != value for key, value in expected_binding.items()):
        raise ValueError("release documentation proposal binding changed")
    record = validate_record(root, plan, proposal["record"], source_paths=source_paths)
    edits = _normalized_edits(documents, proposal["edits"])
    coverage = _validate_coverage(root, proposal["coverage"], documents, source_paths, plan["source_commit"])
    review = proposal["review"]
    checksums = binding.get("checksums")
    protected = {"record": record, "edits": edits, "coverage": coverage, "review": dict(review) if isinstance(review, Mapping) else review}
    expected_checksums = {key: sha256_text(_canonical_json(value)) for key, value in protected.items()}
    if checksums != expected_checksums:
        raise ValueError("release documentation proposal replay content changed")
    updates = {item["path"] for item in coverage if item["disposition"] == "update_recommended"}
    if not updates.issubset({item["path"] for item in edits}):
        raise ValueError("release documentation audit recommends unapplied edits")
    if not isinstance(review, Mapping) or review.get("accepted") is not True or review.get("findings"):
        raise ValueError("release documentation proposal did not pass independent review")
    _evidence(root, review.get("evidence"), source_paths=source_paths, source_commit=plan["source_commit"])
    record_reviews = review.get("record_reviews")
    if not isinstance(record_reviews, list) or not record_reviews:
        raise ValueError("release documentation proposal lacks independent record-review coverage")
    source_chunks = {
        (item["path"], int(chunk["index"]))
        for item in source
        for chunk in chunk_text(item["path"], item["content"], CHUNK_BYTES)
    }
    expected_claims = {name for name, _ in _record_claims(record, source_paths)}
    claim_evidence = review.get("claim_evidence")
    if not isinstance(claim_evidence, list):
        raise ValueError("release documentation proposal lacks claim-evidence coverage")
    claim_sources: dict[str, set[tuple[str, int]]] = {}
    for item in claim_evidence:
        if not isinstance(item, Mapping) or set(item) != {"claim", "source"} or not isinstance(item.get("claim"), str):
            raise ValueError("release documentation claim-evidence has an invalid shape")
        entries = item.get("source")
        if item["claim"] in claim_sources or not isinstance(entries, list) or not entries:
            raise ValueError("release documentation claim-evidence is incomplete")
        keys: set[tuple[str, int]] = set()
        for entry in entries:
            if not isinstance(entry, Mapping) or set(entry) != {"path", "chunk"}:
                raise ValueError("release documentation claim-evidence has an invalid source")
            key = (entry.get("path"), entry.get("chunk"))
            if key not in source_chunks:
                raise ValueError("release documentation claim-evidence names unknown source")
            if (item["claim"] == "summary" or item["claim"].startswith("highlight:")) and key[0] in reference_paths:
                raise ValueError("unchanged reference cannot support a new release summary or highlight")
            keys.add(key)
        claim_sources[item["claim"]] = keys
    if set(claim_sources) != expected_claims:
        raise ValueError("release documentation claim-evidence coverage is incomplete")
    expected_record_reviews = {(claim, path, chunk) for claim, keys in claim_sources.items() for path, chunk in keys}
    reviewed: set[tuple[str, str, int]] = set()
    for item in record_reviews:
        if not isinstance(item, Mapping) or set(item) != {"claim", "path", "chunk", "accepted", "findings", "evidence"}:
            raise ValueError("release documentation record review has an invalid shape")
        key = (item.get("path"), item.get("chunk"))
        claim = item.get("claim")
        if (not isinstance(claim, str) or claim not in expected_claims or key not in source_chunks
                or item.get("accepted") is not True or item.get("findings")):
            raise ValueError("release documentation record review rejected candidate")
        _evidence(root, item.get("evidence"), source_paths=source_paths, source_commit=plan["source_commit"])
        reviewed.add((claim, key[0], key[1]))
    if {item[0] for item in reviewed} != expected_claims or reviewed != expected_record_reviews:
        raise ValueError("release documentation record review coverage is incomplete")
    edit_reviews = review.get("edit_reviews")
    edit_evidence = review.get("edit_evidence")
    if not isinstance(edit_evidence, list):
        raise ValueError("release documentation proposal lacks edit-evidence coverage")
    edit_sources: dict[str, set[tuple[str, int]]] = {}
    for item in edit_evidence:
        if not isinstance(item, Mapping) or set(item) != {"path", "source"} or not isinstance(item.get("path"), str):
            raise ValueError("release documentation edit-evidence has an invalid shape")
        entries = item.get("source")
        if item["path"] in edit_sources or not isinstance(entries, list) or not entries:
            raise ValueError("release documentation edit-evidence is incomplete")
        keys: set[tuple[str, int]] = set()
        for entry in entries:
            if not isinstance(entry, Mapping) or set(entry) != {"path", "chunk"}:
                raise ValueError("release documentation edit-evidence has an invalid source")
            key = (entry.get("path"), entry.get("chunk"))
            if key not in source_chunks:
                raise ValueError("release documentation edit-evidence names unknown source")
            keys.add(key)
        edit_sources[item["path"]] = keys
    if set(edit_sources) != {item["path"] for item in edits}:
        raise ValueError("release documentation edit-evidence coverage is incomplete")
    edit_chunk_map = {
        edit["path"]: {int(chunk["index"]) for chunk in chunk_text(edit["path"], edit["content"], CHUNK_BYTES)}
        for edit in edits
    }
    expected_edit_reviews = {(path, edit_chunk, source_path, source_chunk) for path, keys in edit_sources.items()
                             for edit_chunk in edit_chunk_map[path] for source_path, source_chunk in keys}
    if not isinstance(edit_reviews, list):
        raise ValueError("release documentation edit review coverage is incomplete")
    reviewed_edits: set[tuple[str, int, str, int]] = set()
    for item in edit_reviews:
        if not isinstance(item, Mapping) or set(item) != {"path", "edit_chunk", "source_path", "source_chunk", "accepted", "findings", "evidence"}:
            raise ValueError("release documentation edit review has an invalid shape")
        key = (item.get("path"), item.get("edit_chunk"), item.get("source_path"), item.get("source_chunk"))
        if key not in expected_edit_reviews or item.get("accepted") is not True or item.get("findings"):
            raise ValueError("release documentation edit review rejected candidate")
        _evidence(root, item.get("evidence"), source_paths=source_paths, source_commit=plan["source_commit"])
        reviewed_edits.add(key)
    if reviewed_edits != expected_edit_reviews:
        raise ValueError("release documentation edit review coverage is incomplete")
    return {"record": record, "edits": edits, "coverage": coverage, "review": dict(review), "binding": dict(binding)}
