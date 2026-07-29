from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import re
from typing import Any

import yaml

from ..paths import PathValidationError, validate_repo_relative_path
from ..schema import validate_json_schema
from .models import (
    DomainConfigError,
    DomainDefinition,
    DomainRoot,
    DomainShapesConfig,
    PatternSet,
)

_SCHEMA_RELATIVE_PATH = Path("ls") / "config" / "domain-shapes.schema.json"
_MAX_CONFIG_BYTES = 512 * 1024
_DOMAIN_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")
_GLOB_META = frozenset("*?[")
_DOMAIN_FIELDS = frozenset({"id", "roots", "include", "exclude", "max_files", "max_bytes"})


class _StrictLoader(yaml.SafeLoader):
    pass


def _construct_mapping(
    loader: _StrictLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise DomainConfigError(f"duplicate YAML key: {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def _schema_path(schema_path: Path | str | None) -> Path:
    if schema_path is not None:
        return Path(schema_path)
    return Path(__file__).resolve().parents[2] / "config" / "domain-shapes.schema.json"


def _read_yaml(config_path: Path) -> dict[str, Any]:
    try:
        raw = config_path.read_bytes()
    except OSError as exc:
        raise DomainConfigError(f"could not read domain-shapes config {config_path}: {exc}") from exc
    if len(raw) > _MAX_CONFIG_BYTES:
        raise DomainConfigError(
            f"domain-shapes config exceeds {_MAX_CONFIG_BYTES} bytes: {config_path}",
            issues=(f"config exceeds {_MAX_CONFIG_BYTES} bytes",),
        )
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise DomainConfigError(f"domain-shapes config must be UTF-8: {config_path}") from exc
    try:
        payload = yaml.load(text, Loader=_StrictLoader)
    except DomainConfigError:
        raise
    except yaml.YAMLError as exc:
        raise DomainConfigError(f"domain-shapes config is invalid YAML: {exc}") from exc
    if not isinstance(payload, dict):
        raise DomainConfigError("domain-shapes config must be a YAML mapping")
    return payload


def _schema_issues(payload: dict[str, Any], schema_path: Path) -> list[str]:
    if not schema_path.is_file():
        return [f"domain-shapes schema does not exist: {schema_path}"]
    try:
        return validate_json_schema(
            payload,
            schema_path,
            label="domain-shapes config",
            required=True,
        )
    except (OSError, ValueError) as exc:
        return [f"could not load domain-shapes schema {schema_path}: {exc}"]


def _domain_preflight_issues(payload: Mapping[str, Any]) -> list[str]:
    domains = payload.get("domains")
    if isinstance(domains, Mapping):
        values = domains.values()
    elif isinstance(domains, list):
        values = domains
    else:
        return []

    issues: list[str] = []
    for domain_index, domain in enumerate(values):
        if not isinstance(domain, Mapping):
            continue
        for field in sorted(set(domain) - _DOMAIN_FIELDS):
            issues.append(f"domains[{domain_index}].{field}: Additional properties are not allowed")
        roots = domain.get("roots")
        if not isinstance(roots, list):
            continue
        for root_index, root in enumerate(roots):
            if isinstance(root, Mapping) and root.get("kind") not in {"file", "tree"}:
                issues.append(
                    f"domains[{domain_index}].roots[{root_index}].kind is not one of: file, tree"
                )
    return issues


def _literal_root_path(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise DomainConfigError(f"{field} must be a string")
    normalized = value.replace("\\", "/")
    if normalized == ".":
        return normalized
    try:
        validate_repo_relative_path(normalized, field)
    except PathValidationError as exc:
        raise DomainConfigError(str(exc)) from exc
    if any(character in _GLOB_META for character in normalized):
        raise DomainConfigError(f"{field} must be a literal path, not a glob: {value!r}")
    return normalized


def _pattern_values(value: Any, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise DomainConfigError(f"{field} must be a list")
    patterns: list[str] = []
    for index, item in enumerate(value):
        item_field = f"{field}[{index}]"
        if not isinstance(item, str) or not item:
            raise DomainConfigError(f"{item_field} must be a non-empty string")
        if "\x00" in item:
            raise DomainConfigError(f"{item_field} contains a NUL byte")
        patterns.append(item.replace("\\", "/") if ".glob" in field else item)
    return tuple(patterns)


def _pattern_set(value: Any, field: str) -> PatternSet:
    if value is None:
        value = {}
    if not isinstance(value, Mapping):
        raise DomainConfigError(f"{field} must be a mapping")
    glob_values: list[str] = []
    for key in ("glob", "globs"):
        glob_values.extend(_pattern_values(value.get(key), f"{field}.{key}"))
    regex_values: list[str] = []
    for key in ("regex", "regexes"):
        regex_values.extend(_pattern_values(value.get(key), f"{field}.{key}"))
    issues: list[str] = []
    for index, expression in enumerate(regex_values):
        try:
            re.compile(expression)
        except re.error as exc:
            issues.append(f"{field}.regex[{index}] is invalid: {exc}")
    if issues:
        raise DomainConfigError("; ".join(issues), issues=tuple(issues))
    return PatternSet(glob=tuple(glob_values), regex=tuple(regex_values))


def _parse_payload(payload: dict[str, Any]) -> DomainShapesConfig:
    if "schema_version" in payload:
        schema_version = payload["schema_version"]
        domains_data = [(item["id"], item) for item in payload["domains"]]
    else:
        schema_version = 1
        domains_data = list(payload["domains"].items())
    issues: list[str] = []
    definitions: list[DomainDefinition] = []
    seen: dict[str, int] = {}
    for index, (domain_key, item) in enumerate(domains_data):
        field = f"domains[{index}]"
        domain_id = item.get("id", domain_key)
        if not isinstance(domain_id, str) or _DOMAIN_ID_RE.fullmatch(domain_id) is None:
            issues.append(f"{field}.id must be a stable identifier: {domain_id!r}")
        if domain_id != domain_key and "schema_version" not in payload:
            issues.append(f"{field}.id {domain_id!r} does not match domain key {domain_key!r}")
        if domain_id in seen:
            issues.append(
                f"{field}.id duplicates {domain_id!r} from domains[{seen[domain_id]}].id"
            )
        else:
            seen[domain_id] = index
        try:
            roots = tuple(
                DomainRoot(
                    kind=root_item["kind"],
                    path=_literal_root_path(root_item["path"], f"{field}.roots[{root_index}].path"),
                )
                for root_index, root_item in enumerate(item["roots"])
            )
            include = _pattern_set(item.get("include"), f"{field}.include")
            exclude = _pattern_set(item.get("exclude"), f"{field}.exclude")
            definitions.append(
                DomainDefinition(
                    domain_id=domain_id,
                    roots=roots,
                    include=include,
                    exclude=exclude,
                    max_files=item["max_files"],
                    max_bytes=item["max_bytes"],
                )
            )
        except DomainConfigError as exc:
            issues.extend(exc.issues)
    if issues:
        raise DomainConfigError("; ".join(issues), issues=tuple(issues))
    return DomainShapesConfig(schema_version=schema_version, domains=tuple(definitions))


def load_domain_shapes(
    config_path: Path | str,
    *,
    schema_path: Path | str | None = None,
) -> DomainShapesConfig:
    """Read, schema-check, and semantically validate a domain-shapes YAML file."""

    resolved_config = Path(config_path).expanduser()
    payload = _read_yaml(resolved_config)
    preflight_issues = _domain_preflight_issues(payload)
    if preflight_issues:
        raise DomainConfigError("; ".join(preflight_issues), issues=tuple(preflight_issues))
    resolved_schema = _schema_path(schema_path)
    schema_issues = _schema_issues(payload, resolved_schema)
    if schema_issues:
        raise DomainConfigError("; ".join(schema_issues), issues=tuple(schema_issues))
    try:
        return _parse_payload(payload)
    except (KeyError, TypeError) as exc:
        raise DomainConfigError(f"domain-shapes config has an invalid structure: {exc}") from exc


def validate_domain_shapes(
    config_path: Path | str,
    *,
    schema_path: Path | str | None = None,
) -> dict[str, Any]:
    """Validate a config and return a stable JSON-ready summary."""

    config = load_domain_shapes(config_path, schema_path=schema_path)
    return {
        "ok": True,
        "schema_version": config.schema_version,
        "domains": [definition.domain_id for definition in config.domains],
    }


__all__ = ["load_domain_shapes", "validate_domain_shapes"]
