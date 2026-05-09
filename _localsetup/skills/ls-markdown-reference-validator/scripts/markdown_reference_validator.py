#!/usr/bin/env python3
"""
Markdown reference validator.

Purpose:
- Parse markdown files from configured targets.
- Validate local file-path references discovered in markdown links and code-span path literals.
- Report missing paths and unresolved local anchors.
- Run safely on schedule (interval guard + optional jitter).

Standards:
- Python-first automation per _localsetup/docs/TOOLING_POLICY.md
- Input hardening per _localsetup/docs/INPUT_HARDENING_STANDARD.md
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Pattern

# Localsetup shared dependency guard (approved pattern)
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
from deps import require_deps  # type: ignore  # noqa: E402

require_deps(["yaml"])
import yaml  # noqa: E402

MAX_REASON_LEN = 120
MAX_TEXT_LEN = 2048
DEFAULT_MIN_INTERVAL_SECONDS = 43_200  # 12h
DEFAULT_MAX_FINDINGS = 1000

DEFAULT_PLACEHOLDER_TOKENS = [
    "<repo>",
    "<host>",
    "{slug}",
    "{sub}",
    "{name}",
    "YYYY-MM-DD",
]
DEFAULT_INLINE_CODE_MODE = "smart"
VALID_INLINE_CODE_MODES = {"off", "smart", "all"}

MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
REF_DEF_RE = re.compile(r"^\s*\[[^\]]+\]:\s*(\S+)")
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")
SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
GLOB_META_RE = re.compile(r"[*?\[]")
WINDOWS_ENV_RE = re.compile(r"%[A-Za-z_][A-Za-z0-9_]*%")

URL_LIKE_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
PSEUDO_DOMAIN_PATH_RE = re.compile(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}(/|$)")


@dataclass(frozen=True)
class Finding:
    source_file: str
    line: int
    category: str
    target: str
    resolved_path: str
    detail: str


@dataclass(frozen=True)
class IgnoreRules:
    source_file_globs: list[str]
    target_regexes: list[Pattern[str]]
    path_prefixes: list[str]
    placeholder_tokens: list[str]


@dataclass(frozen=True)
class Config:
    repo_root: Path
    report_path: Path
    state_file: Path
    max_findings: int
    targets: list[dict[str, Any]]
    kilo_manifests: list[str]
    inline_code_mode: str
    ignore: IgnoreRules


class ValidationError(RuntimeError):
    """Raised when configuration cannot be processed safely."""


def _sanitize_text(
    value: Any, *, max_len: int = MAX_TEXT_LEN, fallback: str = ""
) -> str:
    raw = str(value) if value is not None else fallback
    raw = raw.replace("\x00", "")
    cleaned = " ".join(raw.split()).strip()
    return cleaned[:max_len]


def _sanitize_reason(value: str) -> str:
    text = _sanitize_text(value, max_len=MAX_REASON_LEN, fallback="manual")
    return text or "manual"


def _read_epoch(path: Path) -> int:
    if not path.is_file():
        return 0
    raw = path.read_text(encoding="utf-8", errors="replace").strip()
    if not raw:
        return 0
    if not raw.isdigit():
        raise ValidationError(f"State file must contain an epoch integer: {path}")
    return int(raw)


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
    except OSError as exc:
        raise ValidationError(f"Could not read config file: {path} ({exc})") from exc
    except yaml.YAMLError as exc:
        raise ValidationError(f"Invalid YAML in config file: {path} ({exc})") from exc

    if not isinstance(data, dict):
        raise ValidationError("Config root must be a YAML map")
    return data


def _require_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{field} must be a map")
    return value


def _optional_mapping(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key, {})
    if value is None:
        return {}
    return _require_mapping(value, key)


def _optional_string(
    raw: dict[str, Any], key: str, default: str, field: str
) -> str:
    value = raw.get(key, default)
    if value is None:
        value = default
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be a string")
    text = _sanitize_text(value)
    return text or default


def _string_list(
    value: Any, field: str, *, required: bool = False, max_items: int = 200
) -> list[str]:
    if value is None:
        value = []
    if not isinstance(value, list):
        raise ValidationError(f"{field} must be a list of strings")
    out: list[str] = []
    for index, item in enumerate(value[:max_items]):
        if not isinstance(item, str):
            raise ValidationError(f"{field}[{index}] must be a string")
        text = _sanitize_text(item)
        if text:
            out.append(text)
    if required and not out:
        raise ValidationError(f"{field} must contain at least one non-empty string")
    return out


def _optional_bool(raw: dict[str, Any], key: str, field: str) -> bool | None:
    if key not in raw or raw[key] is None:
        return None
    value = raw[key]
    if not isinstance(value, bool):
        raise ValidationError(f"{field} must be true or false")
    return value


def _optional_int(
    raw: dict[str, Any], key: str, default: int, field: str, *, minimum: int = 0
) -> int:
    value = raw.get(key, default)
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValidationError(f"{field} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field} must be an integer") from exc
    if parsed < minimum:
        return minimum
    return parsed


def _expand_template(text: str, *, repo_root: Path) -> str:
    return text.replace("{repo_root}", str(repo_root))


def _normalize_path(value: str, *, cwd: Path, repo_root: Path) -> Path:
    expanded = _expand_template(value, repo_root=repo_root)
    expanded = os.path.expandvars(os.path.expanduser(expanded))
    p = Path(expanded)
    if not p.is_absolute():
        p = (cwd / p).resolve()
    return p


def _compile_regexes(patterns: list[str]) -> list[Pattern[str]]:
    compiled: list[Pattern[str]] = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern))
        except re.error as exc:
            raise ValidationError(
                f"Invalid ignore.target_regexes pattern '{pattern}': {exc}"
            ) from exc
    return compiled


def _validate_targets(targets: Any) -> list[dict[str, Any]]:
    if not isinstance(targets, list) or not targets:
        raise ValidationError("targets must be a non-empty list")

    validated: list[dict[str, Any]] = []
    for index, target in enumerate(targets):
        if not isinstance(target, dict):
            raise ValidationError(f"targets[{index}] must be a map")
        name = _optional_string(
            target, "name", f"target-{index + 1}", f"targets[{index}].name"
        )
        base_dir = _optional_string(
            target, "base_dir", "{repo_root}", f"targets[{index}].base_dir"
        )
        include_globs = _string_list(
            target.get("include_globs"),
            f"targets[{index}].include_globs",
            required=True,
        )
        exclude_globs = _string_list(
            target.get("exclude_globs", []), f"targets[{index}].exclude_globs"
        )
        validated.append(
            {
                "name": name,
                "base_dir": base_dir,
                "include_globs": include_globs,
                "exclude_globs": exclude_globs,
            }
        )
    return validated


def _load_config(config_path: Path) -> Config:
    raw = _load_yaml(config_path)
    fallback_root = Path.cwd().resolve()
    repo_root_raw = _optional_string(raw, "repo_root", str(fallback_root), "repo_root")
    repo_root_raw = _expand_template(repo_root_raw, repo_root=fallback_root)
    repo_root = Path(os.path.expandvars(os.path.expanduser(repo_root_raw))).resolve()

    report = _optional_mapping(raw, "report")
    report_path_raw = _optional_string(
        report,
        "output_path",
        "{repo_root}/docs/reference/markdown-reference-audit.md",
        "report.output_path",
    )
    state_path_raw = _optional_string(
        report,
        "state_file",
        "{repo_root}/.kilo/state/markdown_reference_audit_last_run_epoch",
        "report.state_file",
    )
    max_findings = _optional_int(
        report,
        "max_findings",
        DEFAULT_MAX_FINDINGS,
        "report.max_findings",
        minimum=10,
    )

    targets = _validate_targets(raw.get("targets"))

    manifest_discovery = _optional_mapping(raw, "kilo_manifest_discovery")
    manifests = _string_list(
        manifest_discovery.get("manifests", []),
        "kilo_manifest_discovery.manifests",
    )

    extraction = _optional_mapping(raw, "extraction")
    include_inline_flag = _optional_bool(
        extraction, "include_inline_code_paths", "extraction.include_inline_code_paths"
    )
    inline_code_mode_raw = _optional_string(
        extraction, "inline_code_mode", "", "extraction.inline_code_mode"
    )
    if include_inline_flag is not None and not inline_code_mode_raw:
        inline_code_mode = "smart" if bool(include_inline_flag) else "off"
    else:
        inline_code_mode = (inline_code_mode_raw or DEFAULT_INLINE_CODE_MODE).lower()
    if inline_code_mode not in VALID_INLINE_CODE_MODES:
        raise ValidationError(
            f"extraction.inline_code_mode must be one of {sorted(VALID_INLINE_CODE_MODES)}"
        )

    ignore = _optional_mapping(raw, "ignore")
    source_file_globs = _string_list(
        ignore.get("source_file_globs", []), "ignore.source_file_globs"
    )
    target_regex_strings = _string_list(
        ignore.get("target_regexes", []), "ignore.target_regexes"
    )
    path_prefixes = [
        p.lower()
        for p in _string_list(ignore.get("path_prefixes", []), "ignore.path_prefixes")
    ]
    placeholder_tokens = _string_list(
        ignore.get("placeholder_tokens", []), "ignore.placeholder_tokens"
    )
    if not placeholder_tokens:
        placeholder_tokens = list(DEFAULT_PLACEHOLDER_TOKENS)

    return Config(
        repo_root=repo_root,
        report_path=_normalize_path(
            report_path_raw, cwd=config_path.parent, repo_root=repo_root
        ),
        state_file=_normalize_path(
            state_path_raw, cwd=config_path.parent, repo_root=repo_root
        ),
        max_findings=max_findings,
        targets=targets,
        kilo_manifests=manifests,
        inline_code_mode=inline_code_mode,
        ignore=IgnoreRules(
            source_file_globs=source_file_globs,
            target_regexes=_compile_regexes(target_regex_strings),
            path_prefixes=path_prefixes,
            placeholder_tokens=placeholder_tokens,
        ),
    )


def _collect_glob_files(
    base_dir: Path, patterns: list[str], excludes: list[str]
) -> set[Path]:
    import glob

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
) -> tuple[set[Path], list[str]]:
    discovered: set[Path] = set()
    notes: list[str] = []

    if not manifest_path.is_file():
        notes.append(f"manifest-missing:{manifest_path}")
        return discovered, notes

    try:
        data = _load_json_or_jsonc(manifest_path)
    except json.JSONDecodeError as exc:
        notes.append(f"manifest-invalid-json-or-jsonc:{manifest_path} ({exc})")
        return discovered, notes
    except OSError as exc:
        notes.append(f"manifest-read-error:{manifest_path} ({exc})")
        return discovered, notes

    if not isinstance(data, dict):
        notes.append(f"manifest-invalid-schema:{manifest_path} (root must be object)")
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

    notes.append(f"manifest-ok:{manifest_path}")
    return discovered, notes


def _slugify_heading(text: str) -> str:
    cleaned = text.strip().lower()
    cleaned = re.sub(r"[`*_~\[\]().,:;!?\"'\\/]", "", cleaned)
    cleaned = re.sub(r"\s+", "-", cleaned)
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
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


def _render_report(
    *,
    config_path: Path,
    config: Config,
    reason: str,
    files_scanned: list[Path],
    checked_refs: int,
    findings: list[Finding],
    manifest_notes: list[str],
) -> str:
    ts = datetime.now().astimezone().isoformat(timespec="seconds")

    missing_paths = sum(1 for f in findings if f.category == "missing_path")
    missing_anchors = sum(1 for f in findings if f.category == "missing_anchor")
    read_issues = sum(1 for f in findings if f.category.startswith("unreadable_"))

    lines: list[str] = [
        "# Markdown Reference Audit",
        "",
        f"Updated: {ts}",
        "Status: ACTIVE",
        f"Source: {config_path}",
        f"Auto reason: {reason}",
        "",
        "## Summary",
        "",
        f"- Files scanned: **{len(files_scanned)}**",
        f"- Local references checked: **{checked_refs}**",
        f"- Findings: **{len(findings)}**",
        f"- Missing paths: **{missing_paths}**",
        f"- Missing anchors: **{missing_anchors}**",
        f"- Read issues: **{read_issues}**",
        "",
        "## Config",
        "",
        f"- Repo root: `{config.repo_root}`",
        f"- Report path: `{config.report_path}`",
        f"- State file: `{config.state_file}`",
        f"- Max findings: `{config.max_findings}`",
        f"- Inline code mode: `{config.inline_code_mode}`",
        f"- Ignore source globs: `{len(config.ignore.source_file_globs)}`",
        f"- Ignore target regexes: `{len(config.ignore.target_regexes)}`",
        f"- Ignore path prefixes: `{len(config.ignore.path_prefixes)}`",
        f"- Placeholder tokens: `{len(config.ignore.placeholder_tokens)}`",
        "",
        "## Kilo manifest discovery notes",
        "",
    ]

    if manifest_notes:
        for note in manifest_notes:
            lines.append(f"- {note}")
    else:
        lines.append("- None")

    lines.extend(["", "## Findings", ""])

    if findings:
        lines.extend(
            [
                "| Category | Source | Line | Target | Resolved path | Detail |",
                "|----------|--------|------|--------|---------------|--------|",
            ]
        )
        for f in findings:
            lines.append(
                "| "
                + f"{f.category} | `{f.source_file}` | {f.line} | `{f.target}` | `{f.resolved_path}` | {f.detail} |"
            )
    else:
        lines.append("- No missing local references detected.")

    lines.extend(
        [
            "",
            "## Recommended next steps",
            "",
            "1. Fix missing path findings by updating target paths or creating intended files.",
            "2. Fix missing anchor findings by correcting `#anchor` fragments to match markdown headings.",
            "3. Re-run the audit (`--force`) after updates to confirm a clean result.",
            "",
        ]
    )
    return "\n".join(lines)


def _collect_files(config: Config, config_path: Path) -> tuple[list[Path], list[str]]:
    files: set[Path] = set()
    manifest_notes: list[str] = []

    for target in config.targets:
        if not isinstance(target, dict):
            continue
        base_dir_raw = _sanitize_text(
            target.get("base_dir", "{repo_root}"), fallback="{repo_root}"
        )
        base_dir = _normalize_path(
            base_dir_raw, cwd=config_path.parent, repo_root=config.repo_root
        )
        include = target.get("include_globs", [])
        exclude = target.get("exclude_globs", [])

        include_list = (
            [_sanitize_text(x) for x in include if _sanitize_text(x)]
            if isinstance(include, list)
            else []
        )
        exclude_list = (
            [_sanitize_text(x) for x in exclude if _sanitize_text(x)]
            if isinstance(exclude, list)
            else []
        )
        if not include_list:
            continue

        files |= _collect_glob_files(base_dir, include_list, exclude_list)

    for manifest in config.kilo_manifests:
        manifest_path = _normalize_path(
            manifest, cwd=config_path.parent, repo_root=config.repo_root
        )
        discovered, notes = _discover_manifest_targets(manifest_path, config.repo_root)
        files |= discovered
        manifest_notes.extend(notes)

    sorted_files = sorted(files)
    return sorted_files, manifest_notes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate markdown local references from configured targets."
    )
    parser.add_argument("--config", required=True, help="Path to YAML config")
    parser.add_argument(
        "--report-path", default="", help="Optional report output override"
    )
    parser.add_argument(
        "--state-file", default="", help="Optional state-file path override"
    )
    parser.add_argument(
        "--min-interval-seconds", type=int, default=DEFAULT_MIN_INTERVAL_SECONDS
    )
    parser.add_argument(
        "--force", action="store_true", help="Run regardless of interval guard"
    )
    parser.add_argument("--reason", default="manual", help="Short run reason label")
    parser.add_argument("--jitter-min-seconds", type=int, default=0)
    parser.add_argument("--jitter-max-seconds", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.min_interval_seconds < 60:
        print("[ERROR] --min-interval-seconds must be >= 60", file=sys.stderr)
        return 2

    config_path = Path(args.config).expanduser().resolve()
    if not config_path.is_file():
        print(f"[ERROR] Missing config file: {config_path}", file=sys.stderr)
        return 2

    try:
        config = _load_config(config_path)
    except ValidationError as exc:
        print(f"[ERROR] Invalid config: {exc}", file=sys.stderr)
        return 2

    if args.report_path:
        config = Config(
            repo_root=config.repo_root,
            report_path=_normalize_path(
                args.report_path, cwd=config_path.parent, repo_root=config.repo_root
            ),
            state_file=config.state_file,
            max_findings=config.max_findings,
            targets=config.targets,
            kilo_manifests=config.kilo_manifests,
            inline_code_mode=config.inline_code_mode,
            ignore=config.ignore,
        )

    if args.state_file:
        config = Config(
            repo_root=config.repo_root,
            report_path=config.report_path,
            state_file=_normalize_path(
                args.state_file, cwd=config_path.parent, repo_root=config.repo_root
            ),
            max_findings=config.max_findings,
            targets=config.targets,
            kilo_manifests=config.kilo_manifests,
            inline_code_mode=config.inline_code_mode,
            ignore=config.ignore,
        )

    reason = _sanitize_reason(args.reason)

    try:
        config.state_file.parent.mkdir(parents=True, exist_ok=True)
        config.report_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"[ERROR] Could not create output directories: {exc}", file=sys.stderr)
        return 2

    now_epoch = int(datetime.now().timestamp())
    if not args.force:
        try:
            last_epoch = _read_epoch(config.state_file)
        except (OSError, ValidationError) as exc:
            print(f"[ERROR] Could not read state file: {exc}", file=sys.stderr)
            return 2
        if (now_epoch - last_epoch) < args.min_interval_seconds:
            return 0

    if args.jitter_max_seconds > 0:
        jitter_min = max(0, args.jitter_min_seconds)
        jitter_max = max(jitter_min, args.jitter_max_seconds)
        time.sleep(random.randint(jitter_min, jitter_max))

    files, manifest_notes = _collect_files(config, config_path)
    findings, checked_refs = _extract_findings(
        files,
        repo_root=config.repo_root,
        inline_code_mode=config.inline_code_mode,
        ignore=config.ignore,
        max_findings=config.max_findings,
    )

    report = _render_report(
        config_path=config_path,
        config=config,
        reason=reason,
        files_scanned=files,
        checked_refs=checked_refs,
        findings=findings,
        manifest_notes=manifest_notes,
    )

    try:
        config.report_path.write_text(report, encoding="utf-8")
        config.state_file.write_text(f"{now_epoch}\n", encoding="utf-8")
    except OSError as exc:
        print(f"[ERROR] Could not write audit outputs: {exc}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
