from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class DependencyLedgerError(RuntimeError):
    """Stable, sanitized dependency-ledger failure."""


try:
    import yaml
except ImportError:  # pragma: no cover - mandatory project dependency
    raise DependencyLedgerError("dependency ledger YAML parser is unavailable") from None

from .schema import validate_json_schema


NODE_KINDS = {"skill", "workflow", "resource"}
NODE_ID_RE = re.compile(r"^(skill|workflow|resource):([a-z0-9][a-z0-9-]*)$")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
LEDGER_KEYS = {"schema_version", "nodes", "edges"}
NODE_KEYS = {"id", "kind", "name"}
EDGE_KEYS = {"from", "relation", "to"}


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


def required_skill_closure(repo_root: Path, skill_names: list[str] | set[str]) -> list[str]:
    ledger = load_dependency_ledger(repo_root)
    ledger_skill_names = {node.name for node in ledger.nodes if node.kind == "skill"}
    seed_nodes = {f"skill:{name}" for name in skill_names if name in ledger_skill_names}
    closed_nodes = dependency_closure(ledger, seed_nodes)
    unsupported = sorted(
        node_id for node_id in closed_nodes if not node_id.startswith("skill:")
    )
    if unsupported:
        raise DependencyLedgerError(
            f"unsupported dependency materialization: {unsupported[0]}"
        )
    required = {node_id.removeprefix("skill:") for node_id in closed_nodes}
    return sorted(set(skill_names) | required)
