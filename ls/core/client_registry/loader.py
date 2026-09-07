from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import yaml

from ..paths import PathValidationError, validate_home_scoped_path, validate_repo_relative_path
from ..schema import validate_json_schema
from .models import ClientFamily, ClientRegistry, ClientVariant, freeze
from .qualification import integration_issues


MAX_REGISTRY_BYTES = 512 * 1024


class ClientRegistryError(ValueError):
    pass


class _StrictLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: _StrictLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ClientRegistryError(f"clients.yaml duplicate key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


@dataclass(frozen=True)
class RegistryValidation:
    registry: ClientRegistry | None
    issues: tuple[str, ...]


def _read_yaml(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if len(data) > MAX_REGISTRY_BYTES:
        raise ClientRegistryError(f"clients.yaml exceeds {MAX_REGISTRY_BYTES} bytes")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ClientRegistryError("clients.yaml must be UTF-8") from exc
    try:
        payload = yaml.load(text, Loader=_StrictLoader)
    except yaml.YAMLError as exc:
        raise ClientRegistryError(f"clients.yaml is invalid YAML: {exc}") from exc
    if not isinstance(payload, dict):
        raise ClientRegistryError("clients.yaml must be a mapping")
    return payload


def _surface_issues(surface: dict[str, Any], *, scope: str, field: str) -> list[str]:
    issues: list[str] = []
    status = surface["status"]
    paths = surface["paths"]
    resolution = surface["resolution"]
    setting_label = surface.get("setting_label")
    prefix = f"{field}.{scope}"
    if status == "supported":
        if not paths:
            issues.append(f"{prefix}: supported surface requires paths")
        if resolution in {"settings", "unsupported", "unverified"}:
            issues.append(f"{prefix}: supported surface has incompatible resolution {resolution}")
        if setting_label is not None:
            issues.append(f"{prefix}: supported file surface must not define setting_label")
    elif status == "settings-only":
        if paths or resolution != "settings" or not setting_label:
            issues.append(f"{prefix}: settings-only surface requires settings resolution, setting_label, and no paths")
    else:
        expected = "unsupported" if status == "unsupported" else "unverified"
        if paths or resolution != expected or setting_label is not None:
            issues.append(f"{prefix}: {status} surface must use {expected} resolution and no path or setting")
    if status == "unsupported" and surface["precedence_status"] != "unsupported":
        issues.append(f"{prefix}: unsupported surface requires unsupported precedence")
    for path in paths:
        try:
            if scope == "repo":
                validate_repo_relative_path(path, prefix)
            else:
                _validate_global_path(path, prefix)
        except PathValidationError as exc:
            issues.append(str(exc))
    return issues


def _state_issues(surface: dict[str, Any], *, scope: str, field: str) -> list[str]:
    status = surface["status"]
    path = surface["path"]
    prefix = f"{field}.{scope}"
    if status != "supported":
        return [] if path is None else [f"{prefix}: {status} state must not define a path"]
    if not isinstance(path, str):
        return [f"{prefix}: supported state requires a path"]
    issues: list[str] = []
    try:
        if scope == "repo":
            validate_repo_relative_path(path, prefix)
        else:
            _validate_global_path(path, prefix)
    except PathValidationError as exc:
        issues.append(str(exc))
    normalized = path.replace("\\", "/")
    if not normalized.endswith("/state"):
        issues.append(f"{prefix}: state path must end with /state")
    if any(part in {"skills", "rules", "config"} for part in normalized.split("/")):
        issues.append(f"{prefix}: state path must not be inside a skill, policy, or config directory")
    if Path(normalized).suffix:
        issues.append(f"{prefix}: state path must be a directory")
    return issues


def _insertion_issues(value: dict[str, Any], *, field: str) -> list[str]:
    status = value["status"]
    byte_fields = {
        "encoding", "bom", "frontmatter", "shebang", "native_header", "legal_offset",
        "preserve_mode", "preserve_owner",
    }
    present = byte_fields.intersection(value)
    if status == "supported":
        missing = sorted(byte_fields - present)
        invalid: list[str] = []
        if value.get("preserve_mode") is not True:
            invalid.append("preserve_mode must be true")
        if value.get("preserve_owner") is not True:
            invalid.append("preserve_owner must be true")
        if value.get("shebang") != "reject":
            invalid.append("shebang must be reject")
        if value.get("native_header") != "none":
            invalid.append("native_header must be none")
        if value["collision"] != "owned-block-only":
            invalid.append("collision must be owned-block-only")
        if value["rollback"] != "owned-block-removal":
            invalid.append("rollback must be owned-block-removal")
        if missing or invalid:
            reasons = [*(f"missing {name}" for name in missing), *invalid]
            return [f"{field}: supported insertion has incomplete byte-preservation contract: {', '.join(reasons)}"]
    elif present:
        return [f"{field}: {status} insertion must not define byte-placement fields"]
    elif status == "settings-only" and (value["collision"] != "manual" or value["rollback"] != "manual-settings"):
        return [f"{field}: settings-only insertion requires manual collision and rollback"]
    elif status in {"unsupported", "unverified"} and (value["collision"] != "unsupported" or value["rollback"] != "unsupported"):
        return [f"{field}: {status} insertion requires unsupported collision and rollback"]
    return []


def _validate_global_path(path: str, field: str) -> str:
    if path == "$CODEX_HOME" or path.startswith("$CODEX_HOME/"):
        suffix = path.removeprefix("$CODEX_HOME").lstrip("/")
        if not suffix:
            return path
        validate_repo_relative_path(suffix, field)
        return path
    return validate_home_scoped_path(path, field)


def _paths_overlap(left: str, right: str) -> bool:
    left_parts = tuple(part for part in left.replace("\\", "/").rstrip("/").split("/") if part)
    right_parts = tuple(part for part in right.replace("\\", "/").rstrip("/").split("/") if part)
    shortest = min(len(left_parts), len(right_parts))
    return left_parts[:shortest] == right_parts[:shortest]


def _semantic_issues(payload: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    families = payload["families"]
    family_ids = [str(row["id"]) for row in families]
    if family_ids != sorted(family_ids):
        issues.append("families must be sorted by id")
    if len(family_ids) != len(set(family_ids)):
        issues.append("family ids must be unique")
    platform_ids: list[str] = []
    projection_orders: list[int] = []
    state_owners: dict[tuple[str, str], str] = {}
    for family in families:
        family_id = str(family["id"])
        variants = family["variants"]
        variant_ids = [str(row["id"]) for row in variants]
        if variant_ids != sorted(variant_ids):
            issues.append(f"{family_id}: variants must be sorted by id")
        if len(variant_ids) != len(set(variant_ids)):
            issues.append(f"{family_id}: variant ids must be unique")
        for variant in variants:
            variant_id = str(variant["id"])
            field = f"{family_id}/{variant_id}"
            issues.extend(integration_issues(variant, field=field))
            research = variant["research"]
            if research["status"] in {"verified", "partial"} and not research["sources"]:
                issues.append(f"{field}.research: verified or partial research requires official sources")
            if variant["kind"] == "cli" and not variant["executables"]:
                issues.append(f"{field}.executables: CLI variants require at least one executable")
            for group in ("policy", "config", "skills"):
                for scope in ("repo", "global"):
                    issues.extend(_surface_issues(variant[group][scope], scope=scope, field=f"{field}.{group}"))
            for scope in ("repo", "global"):
                state = variant["state"][scope]
                issues.extend(_state_issues(state, scope=scope, field=f"{field}.state"))
                if state["status"] == "supported":
                    for group in ("policy", "config", "skills"):
                        for surface_path in variant[group][scope]["paths"]:
                            if _paths_overlap(str(state["path"]), str(surface_path)):
                                issues.append(
                                    f"{field}.state.{scope}: state path overlaps {group}.{scope} path {surface_path}"
                                )
                    owner = (scope, str(state["path"]))
                    prior_family = state_owners.get(owner)
                    if prior_family is not None and prior_family != family_id:
                        issues.append(f"{field}.state.{scope}: state path duplicates another family")
                    state_owners[owner] = family_id
            for scope in ("repo", "global"):
                insertion = variant["insertion"][scope]
                issues.extend(_insertion_issues(insertion, field=f"{field}.insertion.{scope}"))
                policy_status = variant["policy"][scope]["status"]
                allowed_insertion = {"supported", "unverified"} if policy_status == "supported" else {policy_status}
                if insertion["status"] not in allowed_insertion:
                    issues.append(
                        f"{field}.insertion.{scope}: status is incompatible with policy discovery status {policy_status}"
                    )
            goal = variant["goal"]
            if goal["status"] == "supported" and (not goal["commands"] or goal["kind"] in {"unsupported", "unverified"}):
                issues.append(f"{field}.goal: supported goal requires commands and a supported kind")
            if goal["status"] != "supported" and goal["commands"]:
                issues.append(f"{field}.goal: unsupported or unverified goal must not define commands")
            if goal["status"] in {"unsupported", "unverified"} and goal["kind"] != goal["status"]:
                issues.append(f"{field}.goal: status and kind must match when unsupported or unverified")
            limits = goal["limits"]
            numeric_limits = {"max_payload_bytes", "max_iterations"}.intersection(limits)
            if limits["status"] == "verified" and not numeric_limits:
                issues.append(f"{field}.goal.limits: verified limits require a numeric limit")
            if limits["status"] != "verified" and numeric_limits:
                issues.append(f"{field}.goal.limits: numeric limits require verified status")
            permissions = variant["permissions"]
            if permissions["status"] == "supported" and not permissions["controls"]:
                issues.append(f"{field}.permissions: supported permissions require controls")
            if permissions["status"] != "supported" and permissions["controls"]:
                issues.append(f"{field}.permissions: unsupported or unverified permissions must not define controls")
            compatibility = variant.get("compatibility")
            if compatibility is None:
                continue
            for scope in ("repo", "global"):
                write_paths = compatibility.get(f"{scope}_write_paths")
                if write_paths is not None and not set(write_paths).issubset(variant["skills"][scope]["paths"]):
                    issues.append(f"{field}.compatibility.{scope}_write_paths: must be a subset of declared skill discovery paths")
            platform_ids.append(str(compatibility["platform_id"]))
            projection_orders.append(int(compatibility["order"]))
            if variant["support_status"] != "supported":
                issues.append(f"{field}.compatibility: only supported variants may project")
            if any(variant["skills"][scope]["status"] != "supported" for scope in ("repo", "global")):
                issues.append(f"{field}.compatibility: projection requires supported repo and global skills")
            if variant["verification"]["classification"] == "unsupported" or variant["rollback"]["classification"] == "unsupported":
                issues.append(f"{field}.compatibility: projection requires verification and rollback")
    if len(platform_ids) != len(set(platform_ids)):
        issues.append("compatibility platform ids must be unique")
    if len(projection_orders) != len(set(projection_orders)):
        issues.append("compatibility projection orders must be unique")
    return sorted(set(issues))


def validate_client_registry(repo_root: Path, *, require_jsonschema: bool = True) -> RegistryValidation:
    config_root = repo_root / "ls" / "config"
    try:
        payload = _read_yaml(config_root / "clients.yaml")
    except (OSError, ClientRegistryError) as exc:
        return RegistryValidation(None, (str(exc),))
    schema_issues = validate_json_schema(
        payload,
        config_root / "clients.schema.json",
        label="clients.yaml",
        required=require_jsonschema,
    )
    if schema_issues:
        return RegistryValidation(None, tuple(schema_issues))
    issues = _semantic_issues(payload)
    if issues:
        return RegistryValidation(None, tuple(issues))
    families = tuple(
        ClientFamily(
            family_id=str(family["id"]),
            display_name=str(family["display_name"]),
            variants=tuple(ClientVariant(str(family["id"]), freeze(variant)) for variant in family["variants"]),
        )
        for family in payload["families"]
    )
    return RegistryValidation(ClientRegistry(int(payload["schema_version"]), families), ())


def load_client_registry(repo_root: Path, *, require_jsonschema: bool = True) -> ClientRegistry:
    result = validate_client_registry(repo_root, require_jsonschema=require_jsonschema)
    if result.registry is None:
        raise ClientRegistryError("; ".join(result.issues))
    return result.registry
