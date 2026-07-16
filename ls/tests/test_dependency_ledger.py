from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from ls.core.dependency_ledger import (
    DependencyLedgerError,
    dependency_closure,
    load_dependency_ledger,
    required_skill_closure,
)
from ls.core.selection import resolve_package_selection
from ls.core.skills import selected_skill_names


ROOT = Path(__file__).resolve().parents[2]


def _fixture_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    config = root / "ls" / "config"
    config.mkdir(parents=True)
    shutil.copy2(ROOT / "ls" / "config" / "dependency-ledger.schema.json", config)
    for name in ("ls-a", "ls-b", "ls-c"):
        skill = root / "ls" / "skills" / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"---\nname: {name}\ndescription: fixture\n---\n", encoding="utf-8")
    workflow = root / "ls" / "workflows" / "ls-workflow-demo"
    workflow.mkdir(parents=True)
    (workflow / "workflow.yaml").write_text("workflow_id: demo\n", encoding="utf-8")
    return root


def _write_ledger(root: Path, *, nodes: list[dict], edges: list[dict]) -> None:
    payload = {"schema_version": 1, "nodes": nodes, "edges": edges}
    (root / "ls" / "config" / "dependency-ledger.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )


def test_dependency_ledger_loads_four_omniroute_nodes_and_stable_closure() -> None:
    ledger = load_dependency_ledger(ROOT)

    assert [node.node_id for node in ledger.nodes] == [
        "skill:ls-omniroute",
        "skill:ls-omniroute-admin-automation",
        "skill:ls-omniroute-proxy",
        "skill:ls-omniroute-update",
    ]
    assert dependency_closure(ledger, {"skill:ls-omniroute"}) == [
        "skill:ls-omniroute",
        "skill:ls-omniroute-admin-automation",
        "skill:ls-omniroute-proxy",
        "skill:ls-omniroute-update",
    ]


@pytest.mark.parametrize(
    ("nodes", "edges", "message"),
    [
        (
            [{"id": "skill:ls-a", "kind": "skill", "name": "ls-a"}] * 2,
            [],
            "duplicate node IDs",
        ),
        (
            [{"id": "skill:ls-a", "kind": "skill", "name": "ls-a"}],
            [{"from": "skill:ls-a", "relation": "requires", "to": "skill:ls-missing"}],
            "dangling node",
        ),
        (
            [{"id": "skill:ls-a", "kind": "skill", "name": "ls-a"}],
            [{"from": "skill:ls-a", "relation": "requires", "to": "skill:ls-a"}],
            "self-referential",
        ),
        (
            [
                {"id": "skill:ls-a", "kind": "skill", "name": "ls-a"},
                {"id": "skill:ls-b", "kind": "skill", "name": "ls-b"},
            ],
            [
                {"from": "skill:ls-a", "relation": "requires", "to": "skill:ls-b"},
                {"from": "skill:ls-b", "relation": "requires", "to": "skill:ls-a"},
            ],
            "requires cycle",
        ),
    ],
)
def test_dependency_ledger_rejects_invalid_graphs(tmp_path: Path, nodes: list[dict], edges: list[dict], message: str) -> None:
    root = _fixture_repo(tmp_path)
    _write_ledger(root, nodes=nodes, edges=edges)

    with pytest.raises(DependencyLedgerError, match=message):
        load_dependency_ledger(root)


def test_dependency_ledger_rejects_mismatched_id_and_preserves_typed_resource(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    _write_ledger(
        root,
        nodes=[{"id": "skill:ls-a", "kind": "skill", "name": "ls-b"}],
        edges=[],
    )
    with pytest.raises(DependencyLedgerError, match="does not match"):
        load_dependency_ledger(root)

    _write_ledger(
        root,
        nodes=[{"id": "resource:not-declared", "kind": "resource", "name": "not-declared"}],
        edges=[],
    )
    ledger = load_dependency_ledger(root)
    assert ledger.nodes[0].node_id == "resource:not-declared"


def test_dependency_ledger_retains_cross_kind_closure_and_selection_rejects_materialization(
    tmp_path: Path,
) -> None:
    root = _fixture_repo(tmp_path)
    nodes = [
        {"id": "skill:ls-a", "kind": "skill", "name": "ls-a"},
        {
            "id": "workflow:ls-workflow-demo",
            "kind": "workflow",
            "name": "ls-workflow-demo",
        },
        {
            "id": "resource:model-snapshot",
            "kind": "resource",
            "name": "model-snapshot",
        },
    ]
    edges = [
        {
            "from": "skill:ls-a",
            "relation": "requires",
            "to": "workflow:ls-workflow-demo",
        },
        {
            "from": "workflow:ls-workflow-demo",
            "relation": "requires",
            "to": "resource:model-snapshot",
        },
    ]
    _write_ledger(root, nodes=nodes, edges=edges)

    ledger = load_dependency_ledger(root)
    assert dependency_closure(ledger, {"skill:ls-a"}) == [
        "resource:model-snapshot",
        "skill:ls-a",
        "workflow:ls-workflow-demo",
    ]
    with pytest.raises(
        DependencyLedgerError,
        match="unsupported dependency materialization: resource:model-snapshot",
    ):
        required_skill_closure(root, ["ls-a"])


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"schema_version": 1, "nodes": []}, "unsupported or missing fields"),
        (
            {"schema_version": "1", "nodes": [], "edges": []},
            "schema_version must be 1",
        ),
        (
            {"schema_version": 1, "nodes": {}, "edges": []},
            "nodes and edges must be lists",
        ),
        (
            {"schema_version": 1, "nodes": [{"id": "skill:ls-a"}], "edges": []},
            "unsupported or missing fields",
        ),
    ],
)
def test_dependency_ledger_manual_invariants_are_stable_without_jsonschema(
    tmp_path: Path,
    payload: dict,
    message: str,
) -> None:
    root = _fixture_repo(tmp_path)
    path = root / "ls" / "config" / "dependency-ledger.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(DependencyLedgerError, match=message):
        load_dependency_ledger(root, require_jsonschema=False)


def test_dependency_ledger_requires_readable_schema_with_sanitized_error(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    _write_ledger(
        root,
        nodes=[{"id": "skill:ls-a", "kind": "skill", "name": "ls-a"}],
        edges=[],
    )
    schema = root / "ls" / "config" / "dependency-ledger.schema.json"
    schema.unlink()

    with pytest.raises(
        DependencyLedgerError,
        match="dependency ledger schema is missing or unsafe",
    ) as captured:
        load_dependency_ledger(root, require_jsonschema=False)
    assert str(root) not in str(captured.value)


def test_pack_and_explicit_selection_restore_hard_omniroute_dependencies() -> None:
    assert {"ls-omniroute", "ls-omniroute-admin-automation", "ls-omniroute-proxy", "ls-omniroute-update"} <= set(
        selected_skill_names(ROOT, ["omniroute"])
    )

    selected = resolve_package_selection(
        ROOT,
        preset="custom",
        skills=["ls-omniroute"],
        exclude_skills=["ls-omniroute-proxy"],
    )
    assert selected.skills == [
        "ls-omniroute",
        "ls-omniroute-admin-automation",
        "ls-omniroute-proxy",
        "ls-omniroute-update",
    ]
