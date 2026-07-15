"""Markdown link and anchor scanning helpers."""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from markdown_reference_config import Finding, IgnoreRules

MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
REF_DEF_RE = re.compile(r"^\s*\[[^\]]+\]:\s*(\S+)")
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")
SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
GLOB_META_RE = re.compile(r"[*?\[]")
WINDOWS_ENV_RE = re.compile(r"%[A-Za-z_][A-Za-z0-9_]*%")
URL_LIKE_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
PSEUDO_DOMAIN_PATH_RE = re.compile(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}(/|$)")

def _slugify_heading(text: str) -> str:
    cleaned = text.strip().lower()
    cleaned = re.sub(r"[`*_~\[\]().,:;!?\"'\\/&]", "", cleaned)
    cleaned = re.sub(r"\s", "-", cleaned)
    cleaned = cleaned.strip("-")
    return cleaned

def _anchors_for_file(
    path: Path, cache: dict[Path, tuple[set[str], str | None]]
) -> tuple[set[str], str | None]:
    if path in cache:
        return cache[path]

    anchors: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        result = (anchors, str(exc))
        cache[path] = result
        return result

    for line in text.splitlines():
        m = HEADING_RE.match(line)
        if m:
            anchors.add(_slugify_heading(m.group(1)))

    result = (anchors, None)
    cache[path] = result
    return result

def _parse_link_target(raw_target: str) -> str:
    value = raw_target.strip()
    if value.startswith("<") and value.endswith(">"):
        inner = value[1:-1].strip()
        if (
            " " in inner
            or SCHEME_RE.match(inner)
            or "/" in inner
            or inner.startswith((".", "~"))
        ):
            return inner
        # Preserve placeholders like <repo> so ignore.placeholder_tokens can match.
        return value
    parts = value.split()
    return parts[0].strip() if parts else ""

def _is_external(target: str) -> bool:
    lower = target.lower()
    if lower.startswith(
        ("http://", "https://", "mailto:", "data:", "tel:", "javascript:")
    ):
        return True
    if SCHEME_RE.match(target) and not re.match(r"^[A-Za-z]:[\\/]", target):
        return True
    return False

def _split_target(target: str) -> tuple[str, str | None]:
    if "#" in target:
        path_part, anchor = target.split("#", 1)
    else:
        path_part, anchor = target, None
    return path_part.strip(), anchor

def _resolve_target(target: str, source_file: Path) -> tuple[Path | None, str | None]:
    path_part, anchor = _split_target(target)
    if not path_part:
        return source_file, anchor

    expanded = os.path.expanduser(path_part)
    expanded = os.path.expandvars(expanded)
    p = Path(expanded)
    if not p.is_absolute():
        p = (source_file.parent / p).resolve()
    return p, anchor

def _resolve_repo_root_candidate(target: str, repo_root: Path) -> Path | None:
    path_part, _anchor = _split_target(target)
    if not path_part:
        return None
    if path_part.startswith(("./", "../", "/", "~/")):
        return None

    expanded = os.path.expandvars(os.path.expanduser(path_part))
    p = Path(expanded)
    if p.is_absolute() or re.match(r"^[A-Za-z]:[\\/]", path_part):
        return None
    return (repo_root / p).resolve()

def _path_matches_glob(path: Path, pattern: str) -> bool:
    path_posix = path.as_posix()
    if fnmatch.fnmatch(path_posix, pattern):
        return True
    return fnmatch.fnmatch(path.name, pattern)

def _is_ignored_source(source_file: Path, ignore: IgnoreRules) -> bool:
    if not ignore.source_file_globs:
        return False
    for pattern in ignore.source_file_globs:
        if _path_matches_glob(source_file, pattern):
            return True
    return False

def _has_placeholder(target: str, placeholder_tokens: list[str]) -> bool:
    normalized = target.lower()
    for token in placeholder_tokens:
        if token.lower() in normalized:
            return True
    if WINDOWS_ENV_RE.search(target):
        return True
    if re.search(r"(^|/)\$[A-Za-z_][A-Za-z0-9_]*", target):
        return True
    if "${" in target:
        return True
    return False

def _has_ignored_path_prefix(target: str, prefixes: list[str]) -> bool:
    if not prefixes:
        return False
    lowered = target.lower()
    if lowered.startswith("./"):
        lowered = lowered[2:]
    for prefix in prefixes:
        p = prefix.strip().lower()
        if not p:
            continue
        p = p.rstrip("/")
        if lowered.startswith(p) or lowered.startswith(f"{p}/"):
            return True
    return False

def _is_pseudo_or_pattern_target(target: str) -> bool:
    base = target.strip()
    if not base:
        return False
    if URL_LIKE_RE.match(base) or PSEUDO_DOMAIN_PATH_RE.match(base):
        return True
    if GLOB_META_RE.search(base):
        return True
    return False

def _should_ignore_target(target: str, source_file: Path, ignore: IgnoreRules) -> bool:
    if _is_ignored_source(source_file, ignore):
        return True
    if _has_placeholder(target, ignore.placeholder_tokens):
        return True
    if _has_ignored_path_prefix(target, ignore.path_prefixes):
        return True
    if _is_pseudo_or_pattern_target(target):
        return True
    for pattern in ignore.target_regexes:
        if pattern.search(target):
            return True
    return False

def _maybe_inline_path(candidate: str) -> bool:
    if " " in candidate:
        return False
    if candidate.startswith(("http://", "https://")):
        return False
    if (
        "/" not in candidate
        and not candidate.startswith(".")
        and not candidate.startswith("~")
    ):
        return False
    suffix = Path(candidate.split("#", 1)[0]).suffix.lower()
    return suffix in {
        ".md",
        ".mdc",
        ".py",
        ".sh",
        ".yaml",
        ".yml",
        ".json",
        ".jsonc",
        ".txt",
    }

def _extract_findings(
    files: list[Path],
    *,
    repo_root: Path,
    inline_code_mode: str,
    ignore: IgnoreRules,
    max_findings: int,
) -> tuple[list[Finding], int]:
    findings: list[Finding] = []
    checked_refs = 0
    seen: set[tuple[str, int, str, str]] = set()
    anchor_cache: dict[Path, tuple[set[str], str | None]] = {}

    for file_path in files:
        if _is_ignored_source(file_path, ignore):
            continue

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            key = (str(file_path), 0, str(file_path), "unreadable-source")
            if key not in seen and len(findings) < max_findings:
                seen.add(key)
                findings.append(
                    Finding(
                        source_file=str(file_path),
                        line=0,
                        category="unreadable_source",
                        target=str(file_path),
                        resolved_path=str(file_path),
                        detail=f"Could not read source markdown: {exc}",
                    )
                )
            continue

        for line_no, line in enumerate(content.splitlines(), 1):
            link_targets = [
                _parse_link_target(m.group(1)) for m in MARKDOWN_LINK_RE.finditer(line)
            ]
            ref_targets = [m.group(1).strip() for m in REF_DEF_RE.finditer(line)]
            all_targets = [t for t in (link_targets + ref_targets) if t]

            if inline_code_mode != "off":
                for cm in INLINE_CODE_RE.finditer(line):
                    code_text = cm.group(1).strip()
                    if not code_text:
                        continue
                    if inline_code_mode == "all" or _maybe_inline_path(code_text):
                        all_targets.append(code_text)

            for target in all_targets:
                if _is_external(target):
                    continue
                if _should_ignore_target(target, file_path, ignore):
                    continue

                checked_refs += 1
                resolved, anchor = _resolve_target(target, file_path)
                resolved_text = str(resolved) if resolved else ""

                if resolved is None:
                    continue

                if not resolved.exists():
                    repo_candidate = _resolve_repo_root_candidate(target, repo_root)
                    if repo_candidate and repo_candidate.exists():
                        continue

                    key = (str(file_path), line_no, target, "missing-path")
                    if key not in seen and len(findings) < max_findings:
                        seen.add(key)
                        findings.append(
                            Finding(
                                source_file=str(file_path),
                                line=line_no,
                                category="missing_path",
                                target=target,
                                resolved_path=resolved_text,
                                detail="Resolved target path does not exist",
                            )
                        )
                    continue

                if (
                    anchor
                    and resolved.is_file()
                    and resolved.suffix.lower() in {".md", ".mdc"}
                ):
                    slug = _slugify_heading(anchor)
                    anchors, anchor_read_error = _anchors_for_file(
                        resolved, anchor_cache
                    )
                    if anchor_read_error:
                        key = (str(file_path), line_no, target, "unreadable-anchor")
                        if key not in seen and len(findings) < max_findings:
                            seen.add(key)
                            findings.append(
                                Finding(
                                    source_file=str(file_path),
                                    line=line_no,
                                    category="unreadable_anchor_target",
                                    target=target,
                                    resolved_path=resolved_text,
                                    detail=(
                                        "Could not read target markdown for anchor "
                                        f"validation: {anchor_read_error}"
                                    ),
                                )
                            )
                        continue
                    if slug and slug not in anchors:
                        key = (str(file_path), line_no, target, "missing-anchor")
                        if key not in seen and len(findings) < max_findings:
                            seen.add(key)
                            findings.append(
                                Finding(
                                    source_file=str(file_path),
                                    line=line_no,
                                    category="missing_anchor",
                                    target=target,
                                    resolved_path=resolved_text,
                                    detail=f"Anchor '#{anchor}' not found in target markdown",
                                )
                            )

    return findings, checked_refs
