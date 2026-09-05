"""Config models and validation helpers for markdown reference audits."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Pattern

import yaml

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

def _display_path(path: Path, *, repo_root: Path) -> str:
    """Render paths for reports without disclosing lexical locations outside the repo."""
    absolute_path = Path(os.path.abspath(path))
    absolute_repo_root = Path(os.path.abspath(repo_root))
    try:
        relative = absolute_path.relative_to(absolute_repo_root)
    except ValueError:
        return "<outside-repo>"
    return relative.as_posix() or "."

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
        "{repo_root}/.localsetup/state/markdown-reference/default.md",
        "report.output_path",
    )
    state_path_raw = _optional_string(
        report,
        "state_file",
        "{repo_root}/.localsetup/state/markdown-reference/default-last-run-epoch",
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
