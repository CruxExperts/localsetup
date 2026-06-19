from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .lockfile import save_json
from .paths import PathValidationError, validate_repo_relative_path
from .provenance import sha256_bytes, source_commit
from .schema import validate_json_schema


MATERIALIZER_VERSION = 1
CLASSIFIER_VERSION = 1
MANIFEST_SCHEMA_VERSION = 1
REFERENCE_BUNDLE_PATH = Path("references/localsetup/.localsetup-reference-bundle.json")
REFERENCE_DOC_ROOT = Path("references/localsetup/docs")
PUBLIC_SOURCE_ALLOWLIST = {"_localsetup/config/pack.yaml"}
MANIFEST_REQUIRED_FIELDS = {
    "schema_version",
    "materializer_version",
    "classifier_version",
    "package_name",
    "package_type",
    "source_path",
    "source_commit",
    "emitter",
    "copied_refs",
    "rewrites",
    "excluded_refs",
    "source_only_metadata",
    "runtime_resolved",
    "validation",
    "digest",
}
PRIVATE_PREFIXES = (
    "_localsetup/docs/local-context/",
    "_localsetup/docs/audits/",
    ".localsetup-maint/",
    "graphify-out/",
    "state/",
    "data/",
    "docs/",
)
PRIVATE_EXACT = {".localsetup-maint", "graphify-out", "state", "data", "docs"}
DOC_REF_RE = re.compile(
    r"(?P<path>(?:_localsetup/docs|\.\./\.\./docs)/[A-Za-z0-9_./%+@~:-]+\.(?:md|json|ya?ml)(?:#[A-Za-z0-9_.:-]+)?)"
)
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
LINK_RE = re.compile(r"(!?\[[^\]]*\]\()([^\)\s]+)(\))")


@dataclass(frozen=True)
class ClassifiedReference:
    original: str
    normalized: str
    category: str
    reason: str


def _normalize_slashes(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _is_configured_private(rel: str, private_paths: list[str]) -> bool:
    normalized = rel.rstrip("/")
    for private in private_paths:
        private_norm = _normalize_slashes(private).rstrip("/")
        if normalized == private_norm or normalized.startswith(private_norm + "/"):
            return True
    return False


def classify_reference(value: str, *, private_paths: list[str] | None = None) -> ClassifiedReference:
    private_paths = private_paths or []
    raw = value.strip()
    path_part, _sep, fragment = raw.partition("#")
    normalized = _normalize_slashes(path_part)
    if normalized.startswith("../") or normalized in {"..", "."}:
        return ClassifiedReference(raw, normalized, "blocked_escape", "parent path references are not portable")
    if normalized:
        try:
            validate_repo_relative_path(normalized, "reference")
        except PathValidationError:
            return ClassifiedReference(raw, normalized, "blocked_escape", "unsafe path")
    if normalized.startswith("references/localsetup/"):
        return ClassifiedReference(raw, normalized, "runtime_resolved", "package-local materialized reference")
    if normalized in PRIVATE_EXACT or any(normalized.startswith(prefix) for prefix in PRIVATE_PREFIXES) or _is_configured_private(normalized, private_paths):
        return ClassifiedReference(raw, normalized, "private_maintenance" if normalized.startswith((".localsetup-maint/", "state/", "data/", "graphify-out/")) else "private_doc", "private path")
    if normalized.startswith("_localsetup/docs/_generated/"):
        return ClassifiedReference(raw, normalized, "generated_public_doc", "generated framework documentation")
    if normalized.startswith("_localsetup/docs/"):
        return ClassifiedReference(raw, normalized, "public_doc", "framework documentation")
    if normalized in PUBLIC_SOURCE_ALLOWLIST:
        return ClassifiedReference(raw, normalized, "public_source_file", "explicit public source allowlist")
    if normalized.startswith("_localsetup/"):
        return ClassifiedReference(raw, normalized, "source_only_metadata", "framework source paths are not runtime package references")
    if fragment and not normalized:
        return ClassifiedReference(raw, normalized, "runtime_resolved", "same-file anchor")
    return ClassifiedReference(raw, normalized, "runtime_resolved", "package-local or external runtime reference")


def _repo_doc_for_ref(
    ref: str,
    source_file: Path,
    source_root: Path,
    repo_root: Path,
    *,
    require_existing: bool = False,
) -> str | None:
    path_part, _sep, _fragment = ref.partition("#")
    normalized = path_part.replace("\\", "/")
    if (
        not normalized.endswith((".md", ".json", ".yaml", ".yml"))
        or any(char.isspace() for char in normalized)
        or any(char in normalized for char in "*<>{}$`")
    ):
        return None
    if normalized.startswith("_localsetup/docs/"):
        if require_existing and not (repo_root / normalized).is_file():
            return None
        return normalized
    if normalized.startswith("../../docs/"):
        candidate = (source_file.parent / normalized).resolve(strict=False)
        docs_root = (repo_root / "_localsetup" / "docs").resolve(strict=False)
        try:
            rel = candidate.relative_to(docs_root).as_posix()
        except ValueError:
            return None
        if require_existing and not candidate.is_file():
            return None
        return f"_localsetup/docs/{rel}"
    if normalized.endswith(".md") and not normalized.startswith(("http://", "https://", "mailto:")):
        candidate = (source_file.parent / normalized).resolve(strict=False)
        docs_root = (repo_root / "_localsetup" / "docs").resolve(strict=False)
        try:
            rel = candidate.relative_to(docs_root).as_posix()
        except ValueError:
            return None
        if not candidate.is_file():
            return None
        return f"_localsetup/docs/{rel}"
    return None


def _bundle_ref(repo_doc_rel: str, fragment: str = "") -> str:
    rel = repo_doc_rel.removeprefix("_localsetup/docs/")
    return (REFERENCE_DOC_ROOT / rel).as_posix() + (f"#{fragment}" if fragment else "")


def _rewrite_markdown_text(
    text: str,
    *,
    source_file: Path,
    source_root: Path,
    repo_root: Path,
    private_paths: list[str],
    copied_refs: set[str],
    excluded_refs: list[dict[str, str]],
    rewrites: list[dict[str, str]],
) -> str:
    in_frontmatter = text.startswith("---\n")
    frontmatter_done = not in_frontmatter
    in_fence = False
    output: list[str] = []
    for index, line in enumerate(text.splitlines(keepends=True)):
        if in_frontmatter:
            output.append(line)
            if index > 0 and line.strip() == "---":
                in_frontmatter = False
                frontmatter_done = True
            continue
        if line.lstrip().startswith("```") or line.lstrip().startswith("~~~"):
            in_fence = not in_fence
            output.append(line)
            continue
        if in_fence or not frontmatter_done:
            output.append(line)
            continue

        def replace_link(match: re.Match[str]) -> str:
            target = match.group(2)
            repo_doc = _repo_doc_for_ref(target, source_file, source_root, repo_root)
            if repo_doc is None:
                return match.group(0)
            _path_part, _sep, fragment = target.partition("#")
            classified = classify_reference(repo_doc, private_paths=private_paths)
            if classified.category not in {"public_doc", "generated_public_doc"}:
                excluded_refs.append({"path": repo_doc, "category": classified.category, "source": str(source_file)})
                if classified.category in {"private_doc", "private_maintenance"}:
                    prefix = match.group(1).replace(target, "omitted-private-reference")
                    return f"{prefix}#localsetup-excluded-reference{match.group(3)}"
                return match.group(0)
            copied_refs.add(repo_doc)
            replacement = _bundle_ref(repo_doc, fragment)
            rewrites.append({"file": str(source_file), "from": target, "to": replacement})
            prefix = match.group(1).replace(target, replacement)
            return f"{prefix}{replacement}{match.group(3)}"

        line = LINK_RE.sub(replace_link, line)

        def replace_inline(match: re.Match[str]) -> str:
            target = match.group(1)
            repo_doc = _repo_doc_for_ref(target, source_file, source_root, repo_root, require_existing=True)
            if repo_doc is None:
                return match.group(0)
            _path_part, _sep, fragment = target.partition("#")
            classified = classify_reference(repo_doc, private_paths=private_paths)
            if classified.category not in {"public_doc", "generated_public_doc"}:
                excluded_refs.append({"path": repo_doc, "category": classified.category, "source": str(source_file)})
                if classified.category in {"private_doc", "private_maintenance"}:
                    return "`omitted-private-reference`"
                return match.group(0)
            copied_refs.add(repo_doc)
            replacement = _bundle_ref(repo_doc, fragment)
            rewrites.append({"file": str(source_file), "from": target, "to": replacement})
            return f"`{replacement}`"

        line = INLINE_CODE_RE.sub(replace_inline, line)

        def replace_bare(match: re.Match[str]) -> str:
            target = match.group("path").rstrip(".,:;")
            suffix = match.group("path")[len(target) :]
            repo_doc = _repo_doc_for_ref(target, source_file, source_root, repo_root, require_existing=True)
            if repo_doc is None:
                return match.group(0)
            classified = classify_reference(repo_doc, private_paths=private_paths)
            if classified.category not in {"public_doc", "generated_public_doc"}:
                excluded_refs.append({"path": repo_doc, "category": classified.category, "source": str(source_file)})
                if classified.category in {"private_doc", "private_maintenance"}:
                    return "omitted-private-reference" + suffix
                return match.group(0)
            copied_refs.add(repo_doc)
            replacement = _bundle_ref(repo_doc)
            rewrites.append({"file": str(source_file), "from": target, "to": replacement})
            return replacement + suffix

        output.append(DOC_REF_RE.sub(replace_bare, line))
    return "".join(output)


def _copy_doc_closure(
    package_root: Path,
    *,
    repo_root: Path,
    private_paths: list[str],
    copied_refs: set[str],
    excluded_refs: list[dict[str, str]],
    rewrites: list[dict[str, str]],
) -> None:
    pending = sorted(copied_refs)
    seen: set[str] = set()
    while pending:
        rel = pending.pop(0)
        if rel in seen:
            continue
        seen.add(rel)
        classified = classify_reference(rel, private_paths=private_paths)
        if classified.category not in {"public_doc", "generated_public_doc"}:
            excluded_refs.append({"path": rel, "category": classified.category, "source": "doc-closure"})
            continue
        src = repo_root / rel
        if not src.is_file():
            excluded_refs.append({"path": rel, "category": "missing", "source": "doc-closure"})
            continue
        dest = package_root / REFERENCE_DOC_ROOT / rel.removeprefix("_localsetup/docs/")
        dest.parent.mkdir(parents=True, exist_ok=True)
        text = src.read_text(encoding="utf-8")
        rewritten = _rewrite_markdown_text(
            text,
            source_file=src,
            source_root=repo_root / "_localsetup" / "docs",
            repo_root=repo_root,
            private_paths=private_paths,
            copied_refs=copied_refs,
            excluded_refs=excluded_refs,
            rewrites=rewrites,
        )
        dest.write_text(rewritten, encoding="utf-8")
        for added in sorted(copied_refs - seen):
            if added not in pending:
                pending.append(added)


def _copy_source_tree(source: Path, destination: Path) -> None:
    source_resolved = source.resolve(strict=True)
    for path in sorted(source.rglob("*")):
        rel = path.relative_to(source)
        if path.is_symlink():
            resolved = path.resolve(strict=True)
            try:
                resolved.relative_to(source_resolved)
            except ValueError as exc:
                raise ValueError(f"package symlink resolves outside package source: {path}") from exc
        target = destination / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def _required_docs(source: Path) -> list[str]:
    manifest = source / "workflow.yaml"
    if not manifest.is_file():
        return []
    data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    raw = data.get("required_docs", []) if isinstance(data, dict) else []
    return [str(item) for item in raw] if isinstance(raw, list) else []


def _source_only_metadata(source: Path, private_paths: list[str]) -> list[dict[str, str]]:
    metadata: list[dict[str, str]] = []
    for doc in _required_docs(source):
        classified = classify_reference(doc, private_paths=private_paths)
        if classified.category in {"private_doc", "private_maintenance", "blocked_escape", "symlink_blocked"}:
            raise ValueError(f"workflow required_docs is not publishable in emitted package: {doc}: {classified.category}")
        metadata.append({"path": doc, "source": "workflow.yaml.required_docs"})
    return metadata


def _manifest_digest(payload: dict[str, Any]) -> str:
    data = {key: value for key, value in payload.items() if key != "digest"}
    return sha256_bytes(json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _validate_manifest_shape(manifest: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    extra_top = sorted(set(manifest) - MANIFEST_REQUIRED_FIELDS)
    if extra_top:
        issues.append(f"reference bundle contains unsupported fields: {', '.join(extra_top)}")
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        issues.append("reference bundle schema_version must be 1")
    for field in ("materializer_version", "classifier_version"):
        if not isinstance(manifest.get(field), int) or manifest.get(field, 0) < 1:
            issues.append(f"reference bundle {field} must be a positive integer")
    for field in ("package_name", "source_path", "source_commit", "emitter", "digest"):
        if not isinstance(manifest.get(field), str) or not manifest.get(field):
            issues.append(f"reference bundle {field} must be a non-empty string")
    if manifest.get("package_type") not in {"skill", "workflow"}:
        issues.append("reference bundle package_type must be skill or workflow")
    for field in ("copied_refs", "runtime_resolved"):
        value = manifest.get(field)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            issues.append(f"reference bundle {field} must be a string list")
    for field in ("rewrites", "excluded_refs", "source_only_metadata"):
        value = manifest.get(field)
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            issues.append(f"reference bundle {field} must be an object list")
    for item in manifest.get("rewrites", []) if isinstance(manifest.get("rewrites"), list) else []:
        extra = sorted(set(item) - {"file", "from", "to"})
        if extra:
            issues.append(f"reference bundle rewrites entries contain unsupported fields: {', '.join(extra)}")
            break
        if not {"file", "from", "to"} <= set(item) or not all(isinstance(item.get(key), str) for key in ("file", "from", "to")):
            issues.append("reference bundle rewrites entries must include string file/from/to")
            break
    for field, required in (
        ("excluded_refs", ("path", "category", "source")),
        ("source_only_metadata", ("path", "source")),
    ):
        for item in manifest.get(field, []) if isinstance(manifest.get(field), list) else []:
            extra = sorted(set(item) - set(required))
            if extra:
                issues.append(f"reference bundle {field} entries contain unsupported fields: {', '.join(extra)}")
                break
            if not set(required) <= set(item) or not all(isinstance(item.get(key), str) for key in required):
                issues.append(f"reference bundle {field} entries must include required string fields")
                break
    validation = manifest.get("validation")
    if not isinstance(validation, dict):
        issues.append("reference bundle validation must be an object")
    else:
        extra_validation = sorted(set(validation) - {"ok", "issues"})
        if extra_validation:
            issues.append(f"reference bundle validation contains unsupported fields: {', '.join(extra_validation)}")
        if not isinstance(validation.get("ok"), bool) or not isinstance(validation.get("issues"), list) or not all(isinstance(item, str) for item in validation.get("issues", [])):
            issues.append("reference bundle validation must include boolean ok and string-list issues")
    return issues


def _manifest_reference_target_issues(package_root: Path, manifest: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    package_resolved = package_root.resolve(strict=False)
    doc_root_resolved = (package_root / REFERENCE_DOC_ROOT).resolve(strict=False)
    for ref in manifest.get("copied_refs", []) if isinstance(manifest.get("copied_refs"), list) else []:
        if not isinstance(ref, str) or not ref.startswith("_localsetup/docs/"):
            continue
        classified = classify_reference(ref)
        if classified.category not in {"public_doc", "generated_public_doc"}:
            issues.append(f"reference bundle copied_ref is not a public doc: {ref}: {classified.category}")
            continue
        target = package_root / REFERENCE_DOC_ROOT / ref.removeprefix("_localsetup/docs/")
        try:
            target.resolve(strict=False).relative_to(doc_root_resolved)
        except ValueError:
            issues.append(f"reference bundle copied_ref target escapes bundled docs: {ref} -> {target.relative_to(package_root)}")
            continue
        if not target.is_file():
            issues.append(f"reference bundle copied_ref target is missing: {ref} -> {target.relative_to(package_root)}")
    for item in manifest.get("rewrites", []) if isinstance(manifest.get("rewrites"), list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("to"), str):
            continue
        target_text = item["to"]
        target_path, _sep, _fragment = target_text.partition("#")
        if not target_path.startswith(REFERENCE_DOC_ROOT.as_posix() + "/"):
            continue
        target = package_root / target_path
        try:
            target.resolve(strict=False).relative_to(package_resolved)
            target.resolve(strict=False).relative_to(doc_root_resolved)
        except ValueError:
            issues.append(f"reference bundle rewrite target escapes bundled docs: {target_text}")
            continue
        if not target.is_file():
            issues.append(f"reference bundle rewrite target is missing: {target_text}")
    return issues


def materialize_package_artifact(
    repo_root: Path,
    source: Path,
    destination: Path,
    *,
    package_name: str,
    package_type: str,
    private_paths: list[str] | None = None,
    emitter: str,
) -> dict[str, Any]:
    private_paths = private_paths or []
    if not source.is_dir():
        raise ValueError(f"missing package source: {source}")
    source_only_metadata = _source_only_metadata(source, private_paths)
    if destination.is_symlink():
        destination.unlink()
    elif destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    _copy_source_tree(source, destination)

    copied_refs: set[str] = set()
    excluded_refs: list[dict[str, str]] = []
    rewrites: list[dict[str, str]] = []
    for md_path in sorted(destination.rglob("*.md")):
        if REFERENCE_BUNDLE_PATH.as_posix() in md_path.as_posix():
            continue
        rel = md_path.relative_to(destination)
        src_equivalent = source / rel
        text = md_path.read_text(encoding="utf-8")
        md_path.write_text(
            _rewrite_markdown_text(
                text,
                source_file=src_equivalent,
                source_root=source,
                repo_root=repo_root,
                private_paths=private_paths,
                copied_refs=copied_refs,
                excluded_refs=excluded_refs,
                rewrites=rewrites,
            ),
            encoding="utf-8",
        )

    _copy_doc_closure(
        destination,
        repo_root=repo_root,
        private_paths=private_paths,
        copied_refs=copied_refs,
        excluded_refs=excluded_refs,
        rewrites=rewrites,
    )
    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "materializer_version": MATERIALIZER_VERSION,
        "classifier_version": CLASSIFIER_VERSION,
        "package_name": package_name,
        "package_type": package_type,
        "source_path": str(source.relative_to(repo_root) if source.is_relative_to(repo_root) else source),
        "source_commit": source_commit(repo_root),
        "emitter": emitter,
        "copied_refs": sorted(copied_refs),
        "rewrites": rewrites,
        "excluded_refs": excluded_refs,
        "source_only_metadata": source_only_metadata,
        "runtime_resolved": [],
        "validation": {"ok": True, "issues": []},
        "digest": "0" * 64,
    }
    manifest_path = destination / REFERENCE_BUNDLE_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    save_json(manifest_path, manifest)
    manifest["validation"] = validate_materialized_package(destination, repo_root=repo_root, check_digest=False)
    if not manifest["validation"]["ok"]:
        save_json(manifest_path, manifest)
        raise ValueError(f"materialized package validation failed: {destination}: {manifest['validation']['issues']}")
    manifest["digest"] = _manifest_digest(manifest)
    save_json(manifest_path, manifest)
    return manifest


def _manifest_for_package(package_root: Path) -> dict[str, Any] | None:
    path = package_root / REFERENCE_BUNDLE_PATH
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"_invalid": "invalid JSON"}
    return payload if isinstance(payload, dict) else {"_invalid": "manifest must be an object"}


def validate_materialized_package(package_root: Path, *, repo_root: Path | None = None, check_digest: bool = True) -> dict[str, Any]:
    issues: list[str] = []
    root = package_root.resolve(strict=True)
    for path in package_root.rglob("*"):
        rel = path.relative_to(package_root).as_posix()
        if rel.startswith((".localsetup-maint/", "graphify-out/", "state/", "_localsetup/docs/local-context/", "_localsetup/docs/audits/")):
            issues.append(f"materialized package contains private or unsafe path: {rel}")
        if path.is_symlink():
            try:
                path.resolve(strict=True).relative_to(root)
            except (FileNotFoundError, ValueError):
                issues.append(f"materialized package symlink escapes package root: {rel}")
    manifest = _manifest_for_package(package_root)
    if manifest is None:
        issues.append(f"missing transform manifest: {REFERENCE_BUNDLE_PATH.as_posix()}")
    elif manifest.get("_invalid"):
        issues.append(str(manifest["_invalid"]))
    else:
        missing = sorted(MANIFEST_REQUIRED_FIELDS - set(manifest))
        if missing:
            issues.append(f"reference bundle missing fields: {', '.join(missing)}")
        issues.extend(_validate_manifest_shape(manifest))
        if repo_root is not None:
            issues.extend(
                validate_json_schema(
                    manifest,
                    repo_root / "_localsetup" / "config" / "reference-bundle.schema.json",
                    label="reference bundle",
                    required=True,
                )
            )
        expected = _manifest_digest(manifest)
        if check_digest and manifest.get("digest") != expected:
            issues.append("reference bundle digest mismatch")
        issues.extend(_manifest_reference_target_issues(package_root, manifest))

    for md_path in package_root.rglob("*.md"):
        if REFERENCE_BUNDLE_PATH.as_posix() in md_path.as_posix():
            continue
        text = md_path.read_text(encoding="utf-8")
        in_frontmatter = text.startswith("---\n")
        in_fence = False
        for index, line in enumerate(text.splitlines()):
            if in_frontmatter:
                if index > 0 and line.strip() == "---":
                    in_frontmatter = False
                continue
            if line.lstrip().startswith("```") or line.lstrip().startswith("~~~"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            for match in DOC_REF_RE.finditer(line):
                classified = classify_reference(match.group("path"))
                if classified.category == "blocked_escape":
                    issues.append(f"unsafe runtime doc reference in {md_path.relative_to(package_root)}: {match.group('path')}")
            for match in LINK_RE.finditer(line):
                target = match.group(2)
                if DOC_REF_RE.fullmatch(target):
                    issues.append(f"unmaterialized runtime doc reference in {md_path.relative_to(package_root)}: {target}")
    return {"ok": not issues, "issues": issues}
