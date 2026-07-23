from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class DependencyLedgerError(RuntimeError):
    """Stable, sanitized dependency-ledger failure."""


try:
    import yaml
except ImportError:  # pragma: no cover - mandatory project dependency
    raise DependencyLedgerError("dependency ledger YAML parser is unavailable") from None

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - mandatory project dependency
    Draft202012Validator = None

from .schema import validate_json_schema


NODE_KINDS = {"skill", "workflow", "resource"}
NODE_ID_RE = re.compile(r"^(skill|workflow|resource):([a-z0-9][a-z0-9-]*)$")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
EVIDENCE_ID_RE = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")
LEDGER_KEYS = {"schema_version", "nodes", "edges"}
NODE_KEYS = {"id", "kind", "name"}
EDGE_KEYS = {"from", "relation", "to"}
RESOURCE_MANIFEST_KEYS = {
    "schema_version",
    "resource_id",
    "owner_skill",
    "schema_path",
    "snapshot_path",
    "matrix_schema_sha256",
    "snapshot_sha256",
    "evidence",
}
RESOURCE_PATH_RE = re.compile(r"^[a-z0-9][a-z0-9-]*(?:\.[a-z0-9]+)?$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_STATIC_RESOURCE_BYTES = 1_048_576


@dataclass(frozen=True)
class DependencyNode:
    node_id: str
    kind: str
    name: str


@dataclass(frozen=True)
class DependencyEdge:
    source: str
    relation: str
    target: str


@dataclass(frozen=True)
class DependencyLedger:
    schema_version: int
    nodes: tuple[DependencyNode, ...]
    edges: tuple[DependencyEdge, ...]


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise DependencyLedgerError("dependency ledger is missing or unsafe")
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise DependencyLedgerError("dependency ledger could not be read") from None
    if not isinstance(payload, dict):
        raise DependencyLedgerError("dependency ledger must be a mapping")
    return payload


def _load_schema(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise DependencyLedgerError("dependency ledger schema is missing or unsafe")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise DependencyLedgerError("dependency ledger schema could not be read") from None
    if not isinstance(payload, dict):
        raise DependencyLedgerError("dependency ledger schema must be an object")
    return payload


def _exact_keys(row: dict[str, Any], expected: set[str], label: str) -> None:
    if set(row) != expected:
        raise DependencyLedgerError(f"{label} has unsupported or missing fields")


def _manual_rows(payload: dict[str, Any]) -> tuple[list[DependencyNode], list[DependencyEdge]]:
    _exact_keys(payload, LEDGER_KEYS, "dependency ledger")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise DependencyLedgerError("dependency ledger schema_version must be 1")
    raw_nodes = payload["nodes"]
    raw_edges = payload["edges"]
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise DependencyLedgerError("dependency ledger nodes and edges must be lists")

    nodes: list[DependencyNode] = []
    for row in raw_nodes:
        if not isinstance(row, dict):
            raise DependencyLedgerError("dependency ledger node must be a mapping")
        _exact_keys(row, NODE_KEYS, "dependency ledger node")
        node_id = row["id"]
        kind = row["kind"]
        name = row["name"]
        if not all(isinstance(value, str) for value in (node_id, kind, name)):
            raise DependencyLedgerError("dependency ledger node fields must be strings")
        if kind not in NODE_KINDS or not NAME_RE.fullmatch(name):
            raise DependencyLedgerError("dependency ledger node kind or name is invalid")
        match = NODE_ID_RE.fullmatch(node_id)
        if match is None or node_id != f"{kind}:{name}":
            raise DependencyLedgerError("dependency ledger node ID does not match kind/name")
        nodes.append(DependencyNode(node_id=node_id, kind=kind, name=name))

    edges: list[DependencyEdge] = []
    for row in raw_edges:
        if not isinstance(row, dict):
            raise DependencyLedgerError("dependency ledger edge must be a mapping")
        _exact_keys(row, EDGE_KEYS, "dependency ledger edge")
        source = row["from"]
        relation = row["relation"]
        target = row["to"]
        if not all(isinstance(value, str) for value in (source, relation, target)):
            raise DependencyLedgerError("dependency ledger edge fields must be strings")
        if relation != "requires":
            raise DependencyLedgerError("dependency ledger relation must be requires")
        if NODE_ID_RE.fullmatch(source) is None or NODE_ID_RE.fullmatch(target) is None:
            raise DependencyLedgerError("dependency ledger edge node ID is invalid")
        edges.append(DependencyEdge(source=source, relation=relation, target=target))
    return nodes, edges


def _declared_names(repo_root: Path, kind: str) -> set[str] | None:
    if kind == "skill":
        return {
            path.parent.name
            for path in (repo_root / "ls" / "skills").glob("*/SKILL.md")
        }
    if kind == "workflow":
        return {
            path.parent.name
            for path in (repo_root / "ls" / "workflows").glob("*/workflow.yaml")
        }
    # R00 preserves resource nodes as typed ledger obligations. R01 will add
    # the package-bundled resource source manifest and materializer.
    return None


def _cycle(nodes: set[str], adjacency: dict[str, tuple[str, ...]]) -> list[str] | None:
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def visit(node_id: str) -> list[str] | None:
        if node_id in visiting:
            start = stack.index(node_id)
            return [*stack[start:], node_id]
        if node_id in visited:
            return None
        visiting.add(node_id)
        stack.append(node_id)
        for target in adjacency.get(node_id, ()):
            found = visit(target)
            if found is not None:
                return found
        stack.pop()
        visiting.remove(node_id)
        visited.add(node_id)
        return None

    for node_id in sorted(nodes):
        found = visit(node_id)
        if found is not None:
            return found
    return None


def load_dependency_ledger(
    repo_root: Path,
    *,
    require_jsonschema: bool = True,
) -> DependencyLedger:
    config_root = repo_root / "ls" / "config"
    ledger_path = config_root / "dependency-ledger.yaml"
    schema_path = config_root / "dependency-ledger.schema.json"
    payload = _load_yaml_mapping(ledger_path)
    _load_schema(schema_path)
    nodes, edges = _manual_rows(payload)
    if require_jsonschema:
        try:
            schema_issues = validate_json_schema(
                payload,
                schema_path,
                label="dependency-ledger.yaml",
                required=True,
            )
        except Exception:
            raise DependencyLedgerError("dependency ledger schema validation failed") from None
        if schema_issues:
            raise DependencyLedgerError("dependency ledger schema validation failed")

    node_ids = [node.node_id for node in nodes]
    if len(node_ids) != len(set(node_ids)):
        raise DependencyLedgerError("dependency ledger contains duplicate node IDs")
    for node in nodes:
        declared = _declared_names(repo_root, node.kind)
        if declared is not None and node.name not in declared:
            raise DependencyLedgerError("dependency ledger node is not declared")

    edge_keys = [(edge.source, edge.relation, edge.target) for edge in edges]
    if len(edge_keys) != len(set(edge_keys)):
        raise DependencyLedgerError("dependency ledger contains duplicate edges")
    known = set(node_ids)
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in known}
    for edge in edges:
        if edge.source == edge.target:
            raise DependencyLedgerError("dependency edge is self-referential")
        if edge.source not in known or edge.target not in known:
            raise DependencyLedgerError("dependency edge references a dangling node")
        adjacency[edge.source].append(edge.target)
    stable_adjacency = {
        node_id: tuple(sorted(targets)) for node_id, targets in adjacency.items()
    }
    found_cycle = _cycle(known, stable_adjacency)
    if found_cycle is not None:
        raise DependencyLedgerError("dependency ledger contains a requires cycle")
    return DependencyLedger(
        schema_version=1,
        nodes=tuple(sorted(nodes, key=lambda node: node.node_id)),
        edges=tuple(
            sorted(edges, key=lambda edge: (edge.source, edge.relation, edge.target))
        ),
    )


def dependency_closure(
    ledger: DependencyLedger,
    node_ids: list[str] | set[str],
) -> list[str]:
    known = {node.node_id for node in ledger.nodes}
    selected = set(node_ids)
    if selected - known:
        raise DependencyLedgerError("dependency closure contains an unknown node")
    adjacency: dict[str, list[str]] = {}
    for edge in ledger.edges:
        adjacency.setdefault(edge.source, []).append(edge.target)
    pending = sorted(selected)
    while pending:
        source = pending.pop(0)
        for target in sorted(adjacency.get(source, [])):
            if target not in selected:
                selected.add(target)
                pending.append(target)
        pending.sort()
    return sorted(selected)


def _resource_identity(metadata: Any) -> tuple[int, int, int]:
    return metadata.st_dev, metadata.st_ino, metadata.st_mode


def _valid_resource_component(name: str, *, pattern: re.Pattern[str] | None = None) -> bool:
    if not isinstance(name, str) or name in {"", ".", ".."} or "\x00" in name or "/" in name or "\\" in name:
        return False
    return pattern is None or pattern.fullmatch(name) is not None


def _close_resource_fd(fd: int) -> None:
    try:
        os.close(fd)
    except (OSError, ValueError, TypeError, NotImplementedError):
        raise DependencyLedgerError("resource descriptor cleanup failed") from None


def _capture_resource_entry(
    parent_fd: int,
    name: str,
    *,
    directory: bool,
    label: str,
    pattern: re.Pattern[str] | None = None,
) -> Any:
    if not _valid_resource_component(name, pattern=pattern):
        raise DependencyLedgerError(f"resource {label} path is invalid")
    try:
        metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except (OSError, ValueError, TypeError, NotImplementedError):
        raise DependencyLedgerError(f"resource {label} is missing or unsafe") from None
    if not (stat.S_ISDIR(metadata.st_mode) if directory else stat.S_ISREG(metadata.st_mode)):
        raise DependencyLedgerError(f"resource {label} is missing or unsafe")
    if not directory and not 0 <= metadata.st_size <= MAX_STATIC_RESOURCE_BYTES:
        raise DependencyLedgerError(f"resource {label} is missing or unsafe")
    return metadata


def _open_resource_directory(parent_fd: int, name: str, *, label: str, pattern: re.Pattern[str] | None = None) -> int:
    observed = _capture_resource_entry(parent_fd, name, directory=True, label=label, pattern=pattern)
    fd: int | None = None
    try:
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
        opened = os.fstat(fd)
        if _resource_identity(opened) != _resource_identity(observed) or not stat.S_ISDIR(opened.st_mode):
            raise DependencyLedgerError(f"resource {label} is missing or unsafe")
        return fd
    except (OSError, ValueError, TypeError, AttributeError, NotImplementedError):
        raise DependencyLedgerError(f"resource {label} is missing or unsafe") from None
    finally:
        if fd is not None:
            try:
                if "opened" not in locals() or _resource_identity(opened) != _resource_identity(observed) or not stat.S_ISDIR(opened.st_mode):
                    _close_resource_fd(fd)
            except DependencyLedgerError:
                raise


def _open_absolute_resource_directory(repo_root: Path) -> int:
    absolute = repo_root.absolute()
    if not absolute.is_absolute():
        raise DependencyLedgerError("resource owner tree is missing or unsafe")
    current_fd: int | None = None
    try:
        current_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        root_metadata = os.fstat(current_fd)
        if not stat.S_ISDIR(root_metadata.st_mode):
            raise DependencyLedgerError("resource owner tree is missing or unsafe")
        for component in absolute.parts[1:]:
            child_fd = _open_resource_directory(current_fd, component, label="owner tree")
            parent_fd = current_fd
            current_fd = None
            try:
                _close_resource_fd(parent_fd)
            except DependencyLedgerError:
                try:
                    _close_resource_fd(child_fd)
                except DependencyLedgerError:
                    pass
                raise
            current_fd = child_fd
        result_fd = current_fd
        current_fd = None
        return result_fd
    except (OSError, ValueError, TypeError, AttributeError, NotImplementedError):
        raise DependencyLedgerError("resource owner tree is missing or unsafe") from None
    finally:
        if current_fd is not None:
            _close_resource_fd(current_fd)


def _read_resource_file(parent_fd: int, name: str, *, label: str) -> bytes:
    observed = _capture_resource_entry(parent_fd, name, directory=False, label=label, pattern=RESOURCE_PATH_RE)
    fd: int | None = None
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
        opened = os.fstat(fd)
        if _resource_identity(opened) != _resource_identity(observed) or not stat.S_ISREG(opened.st_mode) or opened.st_size != observed.st_size:
            raise DependencyLedgerError(f"resource {label} is missing or unsafe")
        remaining = observed.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(fd, min(65_536, remaining))
            if not chunk:
                raise DependencyLedgerError(f"resource {label} could not be read")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(fd, 1):
            raise DependencyLedgerError(f"resource {label} could not be read")
        final = os.fstat(fd)
        if _resource_identity(final) != _resource_identity(observed) or final.st_size != observed.st_size:
            raise DependencyLedgerError(f"resource {label} could not be read")
        return b"".join(chunks)
    except (OSError, ValueError, TypeError, AttributeError, NotImplementedError):
        raise DependencyLedgerError(f"resource {label} could not be read") from None
    finally:
        if fd is not None:
            _close_resource_fd(fd)


def _load_resource_json(parent_fd: int, name: str, *, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        data = _read_resource_file(parent_fd, name, label=label)
        value = json.loads(data.decode("utf-8"))
    except DependencyLedgerError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DependencyLedgerError(f"resource {label} could not be read") from exc
    if not isinstance(value, dict):
        raise DependencyLedgerError(f"resource {label} has unsupported or missing fields")
    return value, data


def _resource_owners(ledger: DependencyLedger, resource_id: str, closed_nodes: set[str]) -> list[str]:
    owners = sorted(
        edge.source.removeprefix("skill:")
        for edge in ledger.edges
        if edge.target == resource_id
        and edge.source.startswith("skill:")
        and edge.source in closed_nodes
    )
    if len(owners) != 1:
        raise DependencyLedgerError("resource must have exactly one selected owning skill")
    return owners


def _resource_manifest_root(
    repo_root: Path,
    *,
    resource_name: str,
    owner_skill: str,
) -> tuple[int, dict[str, Any]]:
    current_fd: int | None = _open_absolute_resource_directory(repo_root)
    selected_fd: int | None = None
    selected_manifest: dict[str, Any] | None = None
    try:
        for component, pattern in (("ls", None), ("skills", None), (owner_skill, NAME_RE), ("resources", None)):
            child_fd = _open_resource_directory(current_fd, component, label="owner tree", pattern=pattern)
            parent_fd = current_fd
            current_fd = None
            try:
                _close_resource_fd(parent_fd)
            except DependencyLedgerError:
                try:
                    _close_resource_fd(child_fd)
                except DependencyLedgerError:
                    pass
                raise
            current_fd = child_fd
        try:
            children = sorted(os.listdir(current_fd))
        except (OSError, ValueError, TypeError, NotImplementedError):
            raise DependencyLedgerError("resource owner tree is missing or unsafe") from None
        for child_name in children:
            child_fd = _open_resource_directory(
                current_fd,
                child_name,
                label="owner tree contains an unsafe entry",
                pattern=NAME_RE,
            )
            keep_child = False
            try:
                manifest, _ = _load_resource_json(child_fd, "manifest.json", label="manifest")
                declared = manifest.get("resource_id")
                if not isinstance(declared, str) or declared != child_name:
                    raise DependencyLedgerError("resource manifest ownership does not match resource tree")
                if declared == resource_name:
                    if selected_fd is not None:
                        raise DependencyLedgerError("resource must have exactly one direct manifest")
                    selected_fd = child_fd
                    selected_manifest = manifest
                    keep_child = True
            finally:
                if not keep_child:
                    _close_resource_fd(child_fd)
        if selected_fd is None or selected_manifest is None:
            raise DependencyLedgerError("resource must have exactly one direct manifest")
        result_fd = selected_fd
        selected_fd = None
        return result_fd, selected_manifest
    finally:
        if current_fd is not None:
            _close_resource_fd(current_fd)
        if selected_fd is not None:
            _close_resource_fd(selected_fd)


def _validate_resource_manifest(
    repo_root: Path,
    *,
    resource_name: str,
    owner_skill: str,
) -> None:
    resource_fd, manifest = _resource_manifest_root(
        repo_root, resource_name=resource_name, owner_skill=owner_skill
    )
    try:
        if not isinstance(manifest, dict) or set(manifest) != RESOURCE_MANIFEST_KEYS:
            raise DependencyLedgerError("resource manifest has unsupported or missing fields")
        if manifest.get("schema_version") != 1:
            raise DependencyLedgerError("resource manifest schema_version is invalid")
        if manifest.get("resource_id") != resource_name or manifest.get("owner_skill") != owner_skill:
            raise DependencyLedgerError("resource manifest ownership does not match dependency ledger")
        if not isinstance(manifest.get("evidence"), list) or not manifest["evidence"]:
            raise DependencyLedgerError("resource manifest evidence is invalid")
        evidence_ids: list[str] = []
        for evidence in manifest["evidence"]:
            if (
                not isinstance(evidence, dict)
                or set(evidence) != {"evidence_id", "url", "access_date", "claim_scope"}
                or not isinstance(evidence.get("evidence_id"), str)
                or not EVIDENCE_ID_RE.fullmatch(evidence["evidence_id"])
                or not isinstance(evidence.get("url"), str)
                or not evidence["url"].startswith("https://")
                or not isinstance(evidence.get("access_date"), str)
                or evidence.get("claim_scope") not in {"model_version", "api_family", "client_product", "accounting"}
            ):
                raise DependencyLedgerError("resource manifest evidence is invalid")
            evidence_ids.append(evidence["evidence_id"])
        if len(evidence_ids) != len(set(evidence_ids)):
            raise DependencyLedgerError("resource manifest evidence is invalid")
        if (
            not isinstance(manifest.get("matrix_schema_sha256"), str)
            or not SHA256_RE.fullmatch(manifest["matrix_schema_sha256"])
            or not isinstance(manifest.get("snapshot_sha256"), str)
            or not SHA256_RE.fullmatch(manifest["snapshot_sha256"])
        ):
            raise DependencyLedgerError("resource manifest snapshot digest is invalid")
        try:
            schema, schema_bytes = _load_resource_json(resource_fd, manifest.get("schema_path"), label="schema")
            snapshot, snapshot_bytes = _load_resource_json(resource_fd, manifest.get("snapshot_path"), label="snapshot")
        except DependencyLedgerError:
            raise
        if hashlib.sha256(schema_bytes).hexdigest() != manifest["matrix_schema_sha256"]:
            raise DependencyLedgerError("resource schema digest does not match manifest")
        if hashlib.sha256(snapshot_bytes).hexdigest() != manifest["snapshot_sha256"]:
            raise DependencyLedgerError("resource snapshot digest does not match manifest")
        if snapshot.get("resource_id") != resource_name or snapshot.get("owner_skill") != owner_skill:
            raise DependencyLedgerError("resource snapshot ownership does not match manifest")
        if snapshot.get("$schema") != schema.get("$id"):
            raise DependencyLedgerError("resource snapshot schema reference does not match manifest")
        try:
            if Draft202012Validator is None:
                raise RuntimeError("jsonschema unavailable")
            Draft202012Validator.check_schema(schema)
            issues = list(Draft202012Validator(schema).iter_errors(snapshot))
        except Exception:
            raise DependencyLedgerError("resource snapshot schema validation failed") from None
        if issues:
            raise DependencyLedgerError("resource snapshot schema validation failed")
    finally:
        _close_resource_fd(resource_fd)


def required_skill_closure(repo_root: Path, skill_names: list[str] | set[str]) -> list[str]:
    ledger = load_dependency_ledger(repo_root)
    ledger_skill_names = {node.name for node in ledger.nodes if node.kind == "skill"}
    seed_nodes = {f"skill:{name}" for name in skill_names if name in ledger_skill_names}
    closed_nodes = dependency_closure(ledger, seed_nodes)
    closed_set = set(closed_nodes)
    resources = sorted(node_id for node_id in closed_nodes if node_id.startswith("resource:"))
    unowned_resources = [
        resource_id
        for resource_id in resources
        if len(
            [
                edge
                for edge in ledger.edges
                if edge.target == resource_id
                and edge.source.startswith("skill:")
                and edge.source in closed_set
            ]
        )
        != 1
    ]
    if unowned_resources:
        raise DependencyLedgerError(
            f"unsupported dependency materialization: {unowned_resources[0]}"
        )
    unsupported = sorted(
        node_id
        for node_id in closed_nodes
        if not node_id.startswith(("skill:", "resource:"))
    )
    if unsupported:
        raise DependencyLedgerError(
            f"unsupported dependency materialization: {unsupported[0]}"
        )
    for resource_id in resources:
        resource_name = resource_id.removeprefix("resource:")
        owner_skill = _resource_owners(ledger, resource_id, closed_set)[0]
        _validate_resource_manifest(repo_root, resource_name=resource_name, owner_skill=owner_skill)
    required = {node_id.removeprefix("skill:") for node_id in closed_nodes if node_id.startswith("skill:")}
    return sorted(set(skill_names) | required)
