from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .lockfile import save_json
from .manifests import load_pack_config
from .package_content.copy import copy_source_tree as _copy_source_tree
from .path_contract import resolve_token
from .paths import expand_user_path
from .paths import PathValidationError, validate_repo_relative_path
from .provenance import sha256_bytes, source_commit
from .schema import validate_json_schema


MATERIALIZER_VERSION = 1
CLASSIFIER_VERSION = 1
MANIFEST_SCHEMA_VERSION = 1
REFERENCE_BUNDLE_PATH = Path("references/localsetup/.localsetup-reference-bundle.json")
REFERENCE_DOC_ROOT = Path("references/localsetup/docs")
PUBLIC_SOURCE_ALLOWLIST = {"ls/config/pack.yaml"}
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
    "ls/docs/local-context/",
    "ls/docs/audits/",
    ".localsetup-maint/",
    "graphify-out/",
    "state/",
    "data/",
    "docs/",
)
PRIVATE_EXACT = {".localsetup-maint", "graphify-out", "state", "data", "docs"}
DOC_REF_RE = re.compile(
    r"(?P<path>(?:(?:\./)?ls/docs|\.\./\.\./docs)/[A-Za-z0-9_./%+@~:-]+\.(?:md|json|ya?ml)(?:#[A-Za-z0-9_.:-]+)?)"
)
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
LINK_RE = re.compile(r"(!?\[[^\]]*\]\()([^\)\s]+)(\))")
RESOLVER_TOKEN_RE = re.compile(r"localsetup://(?:doc|tool|package)/[A-Za-z0-9_./%+@~:-]+")
ABSOLUTE_PATH_RE = re.compile(r"(?<![A-Za-z0-9+.-])/(?:[^\s`'\"<>|)]+)")
RAW_LOCALSETUP_PATH_RE = re.compile(
    r"(?<!/)(?P<path>(?:\./)?ls/(?:docs|tools|skills|workflows|config|core|lib|tests|templates)/[^\s`'\"<>|)]+|"
    r"\.\./\.\./docs/[^\s`'\"<>|)]+)"
)
TEXT_SUFFIXES = {".md", ".yaml", ".yml", ".json", ".toml", ".txt", ".sh", ".py", ".cfg", ".ini"}


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


def _normalize_resolver_doc_remainder(remainder: str) -> str:
    normalized = _normalize_slashes(remainder)
    if normalized.startswith("ls/docs/"):
        return normalized
    return f"ls/docs/{normalized}"


def classify_reference(value: str, *, private_paths: list[str] | None = None) -> ClassifiedReference:
    private_paths = private_paths or []
    raw = value.strip()
    if raw.startswith("localsetup://"):
        kind, _sep, remainder = raw.removeprefix("localsetup://").partition("/")
        if kind not in {"doc", "tool", "package"} or not remainder:
            return ClassifiedReference(raw, raw, "blocked_escape", "unsupported resolver token")
        if kind in {"doc", "tool"}:
            token_path = _normalize_resolver_doc_remainder(remainder) if kind == "doc" else remainder
            try:
                validate_repo_relative_path(token_path, f"LocalSetup token {kind}")
            except PathValidationError:
                return ClassifiedReference(raw, raw, "blocked_escape", "unsafe resolver token path")
            if kind == "doc":
                classified = classify_reference(token_path, private_paths=private_paths)
                return ClassifiedReference(raw, token_path, classified.category, "resolver token")
            return ClassifiedReference(raw, raw, "runtime_resolved", "resolver token")
        package, _package_sep, package_rel = remainder.partition("/")
        try:
            validate_repo_relative_path(package, "LocalSetup token package")
            if package_rel:
                validate_repo_relative_path(package_rel, "LocalSetup token package path")
        except PathValidationError:
            return ClassifiedReference(raw, raw, "blocked_escape", "unsafe resolver token path")
        return ClassifiedReference(raw, raw, "runtime_resolved", "resolver token")
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
    if normalized.startswith("ls/docs/_generated/"):
        return ClassifiedReference(raw, normalized, "generated_public_doc", "generated framework documentation")
    if normalized.startswith("ls/docs/"):
        return ClassifiedReference(raw, normalized, "public_doc", "framework documentation")
    if normalized in PUBLIC_SOURCE_ALLOWLIST:
        return ClassifiedReference(raw, normalized, "public_source_file", "explicit public source allowlist")
    if normalized.startswith("ls/"):
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
    if normalized.startswith("ls/docs/"):
        if require_existing and not (repo_root / normalized).is_file():
            return None
        return normalized
    if normalized.startswith("../../docs/"):
        candidate = (source_file.parent / normalized).resolve(strict=False)
        docs_root = (repo_root / "ls" / "docs").resolve(strict=False)
        try:
            rel = candidate.relative_to(docs_root).as_posix()
        except ValueError:
            return None
        if require_existing and not candidate.is_file():
            return None
        return f"ls/docs/{rel}"
    if normalized.endswith(".md") and not normalized.startswith(("http://", "https://", "mailto:")):
        candidate = (source_file.parent / normalized).resolve(strict=False)
        docs_root = (repo_root / "ls" / "docs").resolve(strict=False)
        try:
            rel = candidate.relative_to(docs_root).as_posix()
        except ValueError:
            return None
        if not candidate.is_file():
            return None
        return f"ls/docs/{rel}"
    return None


def _bundle_ref(repo_doc_rel: str, fragment: str = "") -> str:
    rel = repo_doc_rel.removeprefix("ls/docs/")
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


def _rewrite_resolver_tokens(
    text: str,
    *,
    source_file: Path,
    repo_root: Path,
    home: Path,
    runtime_package_root: Path | None,
    private_paths: list[str],
    copied_refs: set[str] | None = None,
    rewrites: list[dict[str, str]],
    runtime_resolved: list[str] | None = None,
) -> str:
    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        body = token.removeprefix("localsetup://")
        kind, _sep, remainder = body.partition("/")
        if kind == "doc":
            repo_doc = _normalize_resolver_doc_remainder(remainder)
            classified = classify_reference(repo_doc, private_paths=private_paths)
            if classified.category not in {"public_doc", "generated_public_doc"}:
                return token
            if copied_refs is not None:
                copied_refs.add(repo_doc)
            replacement = _bundle_ref(repo_doc)
            rewrites.append({"file": str(source_file), "from": token, "to": replacement})
            return replacement
        replacement = str(
            resolve_token(
                token,
                source_root=repo_root,
                home=home,
                package_root=runtime_package_root,
            )
        )
        rewrites.append({"file": str(source_file), "from": token, "to": replacement})
        if kind in {"tool", "package"} and runtime_resolved is not None:
            runtime_resolved.append(replacement)
        return replacement

    return RESOLVER_TOKEN_RE.sub(replace, text)


def _rewrite_legacy_doc_paths(
    text: str,
    *,
    source_file: Path,
    private_paths: list[str],
    copied_refs: set[str],
    rewrites: list[dict[str, str]],
    excluded_refs: list[dict[str, str]] | None = None,
    private_doc_handling: str = "preserve",
) -> str:
    def replace(match: re.Match[str]) -> str:
        target = match.group("path").rstrip(".,:;")
        suffix = match.group("path")[len(target) :]
        normalized = _normalized_framework_source_path(target)
        path_part, _sep, fragment = normalized.partition("#")
        classified = classify_reference(path_part, private_paths=private_paths)
        if classified.category not in {"public_doc", "generated_public_doc"}:
            if excluded_refs is not None and classified.category in {"private_doc", "private_maintenance"}:
                excluded_refs.append({"path": path_part, "category": classified.category, "source": str(source_file)})
            if private_doc_handling == "omit" and classified.category in {"private_doc", "private_maintenance"}:
                return "omitted-private-reference" + suffix
            return match.group(0)
        copied_refs.add(path_part)
        replacement = _bundle_ref(path_part, fragment)
        rewrites.append({"file": str(source_file), "from": target, "to": replacement})
        return replacement + suffix

    return DOC_REF_RE.sub(replace, text)


def _record_source_metadata(
    source_only_metadata: list[dict[str, str]],
    *,
    path: str,
    source: str,
) -> None:
    if any(item.get("path") == path for item in source_only_metadata):
        return
    item = {"path": path, "source": source}
    source_only_metadata.append(item)


def _rewrite_package_local_source_paths(
    text: str,
    *,
    source_root: Path,
    repo_root: Path,
    source_file: Path,
    rewrites: list[dict[str, str]],
) -> str:
    try:
        source_rel = source_root.relative_to(repo_root).as_posix()
    except ValueError:
        return text
    rewritten = text
    for prefix in (source_rel + "/", "./" + source_rel + "/"):
        if prefix not in rewritten:
            continue

        def replace(match: re.Match[str]) -> str:
            raw = match.group("path").rstrip(".,;:]}>)")
            suffix = match.group("path")[len(raw) :]
            rel = _normalize_slashes(raw).removeprefix("./").removeprefix(source_rel + "/")
            rewrites.append({"file": str(source_file), "from": raw, "to": rel})
            return rel + suffix

        rewritten = re.sub(r"(?<!/)(?P<path>" + re.escape(prefix) + r"[^\s`'\"<>|)]+)", replace, rewritten)
    return rewritten


def _rewrite_framework_source_paths(
    text: str,
    *,
    source_root: Path,
    repo_root: Path,
    source_file: Path,
    preserve_doc_paths: bool = False,
    copied_refs: set[str],
    rewrites: list[dict[str, str]],
    runtime_resolved: list[str],
    source_only_metadata: list[dict[str, str]],
    private_paths: list[str],
    excluded_refs: list[dict[str, str]] | None = None,
    private_doc_handling: str = "preserve",
    rewrite_package_local_source_paths: bool = True,
) -> str:
    rewritten = text if preserve_doc_paths else _rewrite_legacy_doc_paths(
        text,
        source_file=source_file,
        private_paths=private_paths,
        copied_refs=copied_refs,
        rewrites=rewrites,
        excluded_refs=excluded_refs,
        private_doc_handling=private_doc_handling,
    )
    if rewrite_package_local_source_paths:
        rewritten = _rewrite_package_local_source_paths(
            rewritten,
            source_root=source_root,
            repo_root=repo_root,
            source_file=source_file,
            rewrites=rewrites,
        )
    tool_pattern = re.compile(r"(?<!/)(?P<path>(?:\./)?ls/tools/[A-Za-z0-9_.@%+-]+)")

    def replace_tool(match: re.Match[str]) -> str:
        matched = match.group("path")
        raw = matched.rstrip(".,;:]}>)")
        suffix = matched[len(raw) :]
        normalized = _normalize_slashes(raw).removeprefix("./")
        replacement = str(repo_root / normalized)
        rewrites.append({"file": str(source_file), "from": raw, "to": replacement})
        runtime_resolved.append(replacement)
        return replacement + suffix

    rewritten = tool_pattern.sub(replace_tool, rewritten)
    for match in RAW_LOCALSETUP_PATH_RE.finditer(rewritten):
        normalized = _normalized_framework_source_path(match.group("path"))
        if normalized.startswith("ls/tools/"):
            continue
        classified = classify_reference(normalized, private_paths=private_paths)
        if classified.category in {"private_doc", "private_maintenance"}:
            continue
        _record_source_metadata(source_only_metadata, path=normalized, source=str(source_file))
    return rewritten


def _rewrite_remaining_legacy_paths(
    package_root: Path,
    *,
    source_root: Path,
    repo_root: Path,
    copied_refs: set[str],
    rewrites: list[dict[str, str]],
    runtime_resolved: list[str],
    source_only_metadata: list[dict[str, str]],
    private_paths: list[str],
) -> None:
    for text_path in sorted(path for path in package_root.rglob("*") if path.is_file() and path.suffix in TEXT_SUFFIXES):
        if REFERENCE_BUNDLE_PATH.as_posix() in text_path.as_posix():
            continue
        rel = text_path.relative_to(package_root)
        source_file = source_root / rel
        text = text_path.read_text(encoding="utf-8")
        rewritten = _rewrite_framework_source_paths(
            text,
            source_root=source_root,
            repo_root=repo_root,
            source_file=source_file,
            preserve_doc_paths=rel.as_posix() == "workflow.yaml",
            copied_refs=copied_refs,
            rewrites=rewrites,
            runtime_resolved=runtime_resolved,
            source_only_metadata=source_only_metadata,
            private_paths=private_paths,
        )
        if rewritten != text:
            text_path.write_text(rewritten, encoding="utf-8")


def _candidate_from_known_root(text: str, *, start: int, root_text: str = "") -> Path:
    end = start + len(root_text)
    while end < len(text) and text[end] not in "`'\"\n\r<>|":
        end += 1
    return Path(text[start:end].rstrip(".,;:]}>)"))


def _existing_prefix(candidate: Path, *, root_text: str) -> Path | None:
    raw = str(candidate)
    search_start = min(len(raw), len(root_text))
    for index in (pos for pos, char in enumerate(raw[search_start:], start=search_start) if char.isspace()):
        prefix = Path(raw[:index].rstrip(".,;:]}>)"))
        if prefix.exists():
            return prefix
    return candidate if candidate.exists() else None


def _is_source_docs_candidate(candidate: Path) -> bool:
    if "ls" not in candidate.parts:
        return False
    index = candidate.parts.index("ls")
    return len(candidate.parts) > index + 1 and candidate.parts[index + 1] == "docs"


def _copy_doc_closure(
    package_root: Path,
    *,
    repo_root: Path,
    home: Path,
    runtime_package_root: Path | None,
    private_paths: list[str],
    copied_refs: set[str],
    excluded_refs: list[dict[str, str]],
    rewrites: list[dict[str, str]],
    runtime_resolved: list[str],
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
        dest = package_root / REFERENCE_DOC_ROOT / rel.removeprefix("ls/docs/")
        dest.parent.mkdir(parents=True, exist_ok=True)
        text = src.read_text(encoding="utf-8")
        text = _rewrite_resolver_tokens(
            text,
            source_file=src,
            repo_root=repo_root,
            home=home,
            runtime_package_root=runtime_package_root,
            private_paths=private_paths,
            copied_refs=copied_refs,
            rewrites=rewrites,
            runtime_resolved=runtime_resolved,
        )
        text = _rewrite_framework_source_paths(
            text,
            source_root=repo_root / "ls" / "docs",
            repo_root=repo_root,
            source_file=src,
            copied_refs=copied_refs,
            rewrites=rewrites,
            runtime_resolved=runtime_resolved,
            source_only_metadata=[],
            private_paths=private_paths,
            excluded_refs=excluded_refs,
            private_doc_handling="omit",
            rewrite_package_local_source_paths=False,
        )
        rewritten = _rewrite_markdown_text(
            text,
            source_file=src,
            source_root=repo_root / "ls" / "docs",
            repo_root=repo_root,
            private_paths=private_paths,
            copied_refs=copied_refs,
            excluded_refs=excluded_refs,
            rewrites=rewrites,
        )
        dest.write_text(rewritten, encoding="utf-8")
        for added in sorted(copied_refs - seen):
            added_path, _sep, _fragment = added.partition("#")
            if added_path not in seen and added_path not in pending:
                pending.append(added_path)


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
        if not isinstance(ref, str) or not ref.startswith("ls/docs/"):
            continue
        classified = classify_reference(ref)
        if classified.category not in {"public_doc", "generated_public_doc"}:
            issues.append(f"reference bundle copied_ref is not a public doc: {ref}: {classified.category}")
            continue
        target = package_root / REFERENCE_DOC_ROOT / ref.removeprefix("ls/docs/")
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


def _normalized_framework_source_path(value: str) -> str:
    normalized = _normalize_slashes(value.rstrip(".,;:]}>)"))
    if normalized.startswith("../../docs/"):
        return "ls/docs/" + normalized.removeprefix("../../docs/")
    return normalized.removeprefix("./")


def _is_allowed_runtime_path(candidate: str, allowed_runtime_paths: set[str]) -> bool:
    return any(candidate == allowed.rstrip("/") or candidate.startswith(allowed.rstrip("/") + "/") for allowed in allowed_runtime_paths)


def _is_allowed_runtime_candidate(candidate: Path, *, root_text: str, allowed_runtime_paths: set[str]) -> bool:
    if _is_allowed_runtime_path(str(candidate), allowed_runtime_paths):
        return True
    existing_prefix = _existing_prefix(candidate, root_text=root_text)
    return existing_prefix is not None and _is_allowed_runtime_path(str(existing_prefix), allowed_runtime_paths)


def materialize_package_artifact(
    repo_root: Path,
    source: Path,
    destination: Path,
    *,
    package_name: str,
    package_type: str,
    private_paths: list[str] | None = None,
    home: Path | None = None,
    runtime_package_root: Path | None = None,
    emitter: str,
) -> dict[str, Any]:
    private_paths = private_paths or []
    if not source.is_dir():
        raise ValueError(f"missing package source: {source}")
    source_only_metadata = _source_only_metadata(source, private_paths)
    home = home or Path.home()
    if destination.is_symlink():
        destination.unlink()
    elif destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    _copy_source_tree(source, destination)

    copied_refs: set[str] = set()
    excluded_refs: list[dict[str, str]] = []
    rewrites: list[dict[str, str]] = []
    runtime_resolved: list[str] = []
    for text_path in sorted(path for path in destination.rglob("*") if path.is_file() and path.suffix in TEXT_SUFFIXES):
        if REFERENCE_BUNDLE_PATH.as_posix() in text_path.as_posix():
            continue
        rel = text_path.relative_to(destination)
        src_equivalent = source / rel
        text = text_path.read_text(encoding="utf-8")
        text_path.write_text(
            _rewrite_resolver_tokens(
                text,
                source_file=src_equivalent,
                repo_root=repo_root,
                home=home,
                runtime_package_root=runtime_package_root,
                private_paths=private_paths,
                copied_refs=copied_refs,
                rewrites=rewrites,
                runtime_resolved=runtime_resolved,
            ),
            encoding="utf-8",
        )

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

    _rewrite_remaining_legacy_paths(
        destination,
        source_root=source,
        repo_root=repo_root,
        copied_refs=copied_refs,
        rewrites=rewrites,
        runtime_resolved=runtime_resolved,
        source_only_metadata=source_only_metadata,
        private_paths=private_paths,
    )
    _copy_doc_closure(
        destination,
        repo_root=repo_root,
        home=home,
        runtime_package_root=runtime_package_root,
        private_paths=private_paths,
        copied_refs=copied_refs,
        excluded_refs=excluded_refs,
        rewrites=rewrites,
        runtime_resolved=runtime_resolved,
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
        "runtime_resolved": sorted(set(runtime_resolved)),
        "validation": {"ok": True, "issues": []},
        "digest": "0" * 64,
    }
    manifest_path = destination / REFERENCE_BUNDLE_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    save_json(manifest_path, manifest)
    manifest["validation"] = validate_materialized_package(
        destination,
        repo_root=repo_root,
        check_digest=False,
        home=home,
        runtime_package_root=runtime_package_root,
    )
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


def validate_materialized_package(
    package_root: Path,
    *,
    repo_root: Path | None = None,
    check_digest: bool = True,
    home: Path | None = None,
    runtime_package_root: Path | None = None,
) -> dict[str, Any]:
    issues: list[str] = []
    root = package_root.resolve(strict=True)
    for path in package_root.rglob("*"):
        rel = path.relative_to(package_root).as_posix()
        if rel.startswith((".localsetup-maint/", "graphify-out/", "state/", "ls/docs/local-context/", "ls/docs/audits/")):
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
                    repo_root / "ls" / "config" / "reference-bundle.schema.json",
                    label="reference bundle",
                    required=True,
                )
            )
        expected = _manifest_digest(manifest)
        if check_digest and manifest.get("digest") != expected:
            issues.append("reference bundle digest mismatch")
        issues.extend(_manifest_reference_target_issues(package_root, manifest))
    manifest_payload = manifest or {}
    allowed_runtime_paths = {
        str(item)
        for item in manifest_payload.get("runtime_resolved", [])
        if isinstance(item, str)
    }
    allowed_runtime_paths.update(
        str(rewrite.get("to"))
        for rewrite in manifest_payload.get("rewrites", [])
        if isinstance(rewrite, dict)
        and str(rewrite.get("from", "")).startswith(("localsetup://tool/", "localsetup://package/"))
    )
    allowed_source_metadata = {
        str(item.get("path"))
        for item in manifest_payload.get("source_only_metadata", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }

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
    localsetup_roots: list[Path] = []
    if repo_root is not None:
        localsetup_roots.append((repo_root / "ls").resolve(strict=False))
        try:
            pack = load_pack_config(repo_root)
            localsetup_roots.append(expand_user_path(pack.package_root, home or Path.home()).resolve(strict=False))
        except Exception:
            pass
    if runtime_package_root is not None:
        localsetup_roots.append(runtime_package_root.expanduser().resolve(strict=False))
    for text_path in sorted(path for path in package_root.rglob("*") if path.is_file() and path.suffix in TEXT_SUFFIXES):
        if REFERENCE_BUNDLE_PATH.as_posix() in text_path.as_posix():
            continue
        rel_text_path = text_path.relative_to(package_root).as_posix()
        if rel_text_path in {".localsetup-managed.json", ".localsetup-managed"}:
            continue
        text = text_path.read_text(encoding="utf-8", errors="replace")
        if RESOLVER_TOKEN_RE.search(text):
            issues.append(f"unresolved resolver token in {text_path.relative_to(package_root)}")
        if rel_text_path.startswith(REFERENCE_DOC_ROOT.as_posix() + "/"):
            continue
        for match in RAW_LOCALSETUP_PATH_RE.finditer(text):
            raw_path = match.group("path")
            normalized = _normalized_framework_source_path(raw_path)
            if normalized in allowed_source_metadata:
                continue
            issues.append(f"forbidden LocalSetup path reference in {text_path.relative_to(package_root)}: {raw_path}")
        for owned_root_path in localsetup_roots:
            owned_root_text = str(owned_root_path)
            cursor = 0
            while True:
                start = text.find(owned_root_text, cursor)
                if start < 0:
                    break
                candidate = _candidate_from_known_root(text, start=start, root_text=owned_root_text)
                cursor = start + max(len(str(candidate)), 1)
                if any(char in str(candidate) for char in "*?["):
                    continue
                if _is_allowed_runtime_candidate(candidate, root_text=owned_root_text, allowed_runtime_paths=allowed_runtime_paths):
                    continue
                if repo_root is not None:
                    source_root = (repo_root / "ls").resolve(strict=False)
                    resolved_candidate = candidate.resolve(strict=False)
                    if resolved_candidate == source_root or source_root in resolved_candidate.parents:
                        issues.append(f"unrecorded LocalSetup absolute path in {text_path.relative_to(package_root)}: {candidate}")
                        continue
                if _existing_prefix(candidate, root_text=owned_root_text) is not None:
                    continue
                if not candidate.exists():
                    issues.append(f"dangling LocalSetup absolute path in {text_path.relative_to(package_root)}: {candidate}")
        for match in ABSOLUTE_PATH_RE.finditer(text):
            raw_candidate = match.group(0).rstrip(".,;:]}>)")
            if raw_candidate.startswith(("/path/to/", "/example/", "/your/", "/ls", "/.local/")):
                continue
            if any(char in raw_candidate for char in "*?["):
                continue
            candidate = Path(raw_candidate)
            resolved_candidate = candidate.resolve(strict=False)
            owned_root = any(resolved_candidate == root or root in resolved_candidate.parents for root in localsetup_roots)
            source_owned = "ls" in candidate.parts and candidate.parts.index("ls") > 1
            if _is_allowed_runtime_path(str(candidate), allowed_runtime_paths):
                continue
            if (source_owned or owned_root) and candidate.exists():
                issues.append(f"unrecorded LocalSetup absolute path in {text_path.relative_to(package_root)}: {candidate}")
            elif source_owned or owned_root:
                issues.append(f"dangling LocalSetup absolute path in {text_path.relative_to(package_root)}: {candidate}")
    return {"ok": not issues, "issues": issues}
