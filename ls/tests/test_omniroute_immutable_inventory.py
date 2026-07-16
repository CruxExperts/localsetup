from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "ls/skills/ls-omniroute-update/scripts/omniroute_inventory.py"
FIXTURE = ROOT / "ls/tests/fixtures/omniroute/immutable-inventory-7ee5bbc.json"
DECISION_SHAPED_PROXY_TOOLS = {
    "omniroute_best_combo_for_task",
    "omniroute_explain_route",
    "omniroute_simulate_route",
}


def _load_inventory():
    spec = importlib.util.spec_from_file_location(
        "omniroute_inventory_under_test", SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _explicit_mirror() -> Path | None:
    value = os.environ.get("LOCALSETUP_OMNIROUTE_MIRROR")
    return Path(value) if value else None


def test_immutable_inventory_matches_full_exact_mirror_contract() -> None:
    mirror = _explicit_mirror()
    if mirror is None:
        pytest.skip("requires explicitly supplied OmniRoute mirror")
    module = _load_inventory()
    inventory = module.build_inventory(mirror, ROOT)
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert inventory["schema_version"] == expected["schema_version"]
    assert inventory["source"] == expected["source"]
    assert inventory["digests"] == expected["digests"]
    assert {
        "skills": len(inventory["skills"]),
        "route_handlers": len(inventory["route_handlers"]),
        "openapi_operations": len(inventory["openapi_operations"]),
        "compatibility_rewrites": len(inventory["compatibility_rewrites"]),
        "registered_tools": len(inventory["registered_tools"]),
        "retained_claims_resolved": len(inventory["retained_claims"]["resolved"]),
        "retained_claims_unresolved": len(inventory["retained_claims"]["unresolved"]),
    } == expected["counts"]
    assert [row["name"] for row in inventory["registered_tools"]] == expected[
        "registered_tool_names"
    ]
    assert inventory["retained_claims"] == expected["retained_claims"]

    for key in (
        "skills",
        "route_handlers",
        "openapi_operations",
        "compatibility_rewrites",
        "registered_tools",
        "retained_claims",
    ):
        assert module._sha256_json(inventory[key]) == expected["digests"][key]
    assert inventory["retained_claims"]["unresolved"] == []
    assert module.CLAIM_EXCEPTIONS == {}

    registered = {row["name"] for row in inventory["registered_tools"]}
    assert DECISION_SHAPED_PROXY_TOOLS <= registered
    for false_positive in (
        "omniroute_admin",
        "omniroute_api",
        "omniroute_discover",
        "omniroute_inventory",
        "omniroute_login_time",
        "omniroute_music",
        "omniroute_proxy",
        "omniroute_update",
    ):
        assert false_positive not in registered
    assert all(row["owners"] for row in inventory["registered_tools"])
    assert all(
        owner["source_path"] in module.TOOL_OWNER_PATHS
        and re.fullmatch(r"[0-9a-f]{40}", owner["source_blob"])
        and re.fullmatch(r"[0-9a-f]{64}", owner["source_sha256"])
        for row in inventory["registered_tools"]
        for owner in row["owners"]
    )
    retained_proxy_claims = {
        row["claim"]
        for row in inventory["retained_claims"]["resolved"]
        if row["package"] == "ls-omniroute-proxy"
    }
    assert not DECISION_SHAPED_PROXY_TOOLS & retained_proxy_claims

    for collection in (inventory["route_handlers"], inventory["openapi_operations"]):
        assert all(row["method"] in module.HTTP_METHODS for row in collection)
        assert all(row["path"].startswith("/") for row in collection)
        assert all(re.fullmatch(r"[0-9a-f]{40}", row["source_blob"]) for row in collection)
        assert all(re.fullmatch(r"[0-9a-f]{64}", row["source_sha256"]) for row in collection)

    rewrites = {(row["source"], row["destination"]) for row in inventory["compatibility_rewrites"]}
    assert ("/v1/:path*", "/api/v1/:path*") in rewrites
    models_claims = [
        row
        for row in inventory["retained_claims"]["resolved"]
        if row["claim"] == "GET /v1/models"
    ]
    assert models_claims
    assert all(row["status"] == "compatible-rewrite" for row in models_claims)
    assert all(row["target"] == "GET /api/v1/models" for row in models_claims)
    assert str(mirror) not in json.dumps(inventory, sort_keys=True)


def test_registered_tool_patterns_reject_plain_text_false_positives() -> None:
    module = _load_inventory()
    text = (
        'const prose = "omniroute_not_registered";\n'
        'server.registerTool("omniroute_registered_direct", {}, handler);\n'
        'const tool = { name: "omniroute_registered_collection" };\n'
    )

    assert module.DIRECT_TOOL_RE.findall(text) == ["omniroute_registered_direct"]
    assert module.NAMED_TOOL_RE.findall(text) == ["omniroute_registered_collection"]
    assert "omniroute_not_registered" not in (
        module.DIRECT_TOOL_RE.findall(text) + module.NAMED_TOOL_RE.findall(text)
    )


def test_immutable_inventory_snapshot_is_well_formed() -> None:
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    module = _load_inventory()

    assert expected["schema_version"] == 3
    assert expected["source"]["tag"] == "v3.8.48"
    assert expected["source"]["tag_object"] == (
        "4f00f84b5a12f90fca2f1d72a60404cf6f5bf059"
    )
    assert expected["source"]["commit"] == (
        "7ee5bbc64dbb03e967521227f2afffeb7c9dad1e"
    )
    assert expected["counts"]["skills"] == 44
    assert expected["counts"]["retained_claims_resolved"] == 97
    assert expected["counts"]["retained_claims_unresolved"] == 0
    assert len(expected["registered_tool_names"]) == expected["counts"]["registered_tools"]
    assert expected["registered_tool_names"] == sorted(
        set(expected["registered_tool_names"])
    )
    assert DECISION_SHAPED_PROXY_TOOLS <= set(expected["registered_tool_names"])
    retained_claims = expected["retained_claims"]
    assert set(retained_claims) == {"resolved", "unresolved"}
    assert retained_claims["unresolved"] == []
    assert len(retained_claims["resolved"]) == expected["counts"]["retained_claims_resolved"]
    assert retained_claims["resolved"] == sorted(
        retained_claims["resolved"],
        key=lambda row: (
            row["package"],
            row["kind"],
            row["claim"],
            row["source_path"],
        ),
    )
    assert all(
        set(row) == {"package", "kind", "claim", "source_path", "status", "target"}
        and row["package"] in module.RETAINED_PACKAGES
        and row["kind"] in {"endpoint", "tool"}
        and row["source_path"].startswith("ls/skills/")
        and not Path(row["source_path"]).is_absolute()
        for row in retained_claims["resolved"]
    )
    assert module._sha256_json(retained_claims) == expected["digests"]["retained_claims"]
    assert str(ROOT) not in json.dumps(retained_claims, sort_keys=True)
    retained_proxy_claims = {
        row["claim"]
        for row in retained_claims["resolved"]
        if row["package"] == "ls-omniroute-proxy"
    }
    assert not DECISION_SHAPED_PROXY_TOOLS & retained_proxy_claims
    for value in expected["digests"].values():
        assert re.fullmatch(r"[0-9a-f]{64}", value)


def test_immutable_inventory_missing_mirror_is_typed_and_sanitized(
    tmp_path: Path,
) -> None:
    module = _load_inventory()

    with pytest.raises(module.InventoryError, match="^inventory_mirror_missing$"):
        module.build_inventory(tmp_path / "missing.git", ROOT)


def test_no_machine_specific_mirror_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOCALSETUP_OMNIROUTE_MIRROR", raising=False)

    assert _explicit_mirror() is None


def _mock_source_provenance(
    module, monkeypatch: pytest.MonkeyPatch, *, tag_object: str | None = None,
    object_type: str = "tag", peel_error: bool = False,
) -> list[str]:
    calls: list[str] = []
    tag_object = tag_object or module.SOURCE_TAG_OBJECT
    values = {
        f"refs/tags/{module.SOURCE_TAG}": tag_object,
        f"{module.SOURCE_TAG_OBJECT}^{{commit}}": module.SOURCE_COMMIT,
        f"{module.SOURCE_COMMIT}^{{tree}}": module.SOURCE_TREE,
        f"{module.SOURCE_COMMIT}:skills": module.SOURCE_SKILLS_TREE,
    }

    def fake_object_id(_git_dir: Path, expression: str) -> str:
        calls.append(expression)
        if peel_error and expression.endswith("^{commit}"):
            raise module.InventoryError("inventory_git_read_failed")
        try:
            return values[expression]
        except KeyError:
            raise module.InventoryError("inventory_git_read_failed") from None

    def fake_git(_git_dir: Path, *args: str, **_kwargs: object) -> str:
        assert args == ("cat-file", "-t", module.SOURCE_TAG_OBJECT)
        return f"{object_type}\n"

    monkeypatch.setattr(module, "_object_id", fake_object_id)
    monkeypatch.setattr(module, "_git", fake_git)
    return calls


def test_source_tag_provenance_is_complete_without_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_inventory()
    calls = _mock_source_provenance(module, monkeypatch)

    source = module._source_provenance(Path("portable.git"))

    assert source == {
        "tag": module.SOURCE_TAG,
        "tag_object": module.SOURCE_TAG_OBJECT,
        "commit": module.SOURCE_COMMIT,
        "tree": module.SOURCE_TREE,
        "skills_tree": module.SOURCE_SKILLS_TREE,
    }
    assert calls == [
        f"refs/tags/{module.SOURCE_TAG}",
        f"{module.SOURCE_TAG_OBJECT}^{{commit}}",
        f"{module.SOURCE_COMMIT}^{{tree}}",
        f"{module.SOURCE_COMMIT}:skills",
    ]


def test_source_tag_missing_is_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_inventory()

    def missing_tag(_git_dir: Path, _expression: str) -> str:
        raise module.InventoryError("inventory_git_read_failed")

    monkeypatch.setattr(module, "_object_id", missing_tag)
    with pytest.raises(module.InventoryError, match="^inventory_source_tag_missing$"):
        module._source_provenance(Path("portable.git"))


def test_source_tag_mismatch_is_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_inventory()
    _mock_source_provenance(module, monkeypatch, tag_object="0" * 40)

    with pytest.raises(module.InventoryError, match="^inventory_source_tag_mismatch$"):
        module._source_provenance(Path("portable.git"))


def test_source_tag_must_be_annotated(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_inventory()
    _mock_source_provenance(module, monkeypatch, object_type="commit")

    with pytest.raises(
        module.InventoryError, match="^inventory_source_tag_not_annotated$"
    ):
        module._source_provenance(Path("portable.git"))


def test_source_tag_peel_failure_is_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_inventory()
    _mock_source_provenance(module, monkeypatch, peel_error=True)

    with pytest.raises(module.InventoryError, match="^inventory_source_tag_peel_failed$"):
        module._source_provenance(Path("portable.git"))


def test_build_inventory_cannot_bypass_source_tag_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_inventory()
    calls: list[str] = []

    def source_provenance(_git_dir: Path) -> dict[str, str]:
        calls.append("source")
        return {}

    def tracked_paths(_git_dir: Path) -> list[str]:
        assert calls == ["source"]
        raise RuntimeError("stop-after-provenance")

    monkeypatch.setattr(module, "_source_provenance", source_provenance)
    monkeypatch.setattr(module, "_tracked_paths", tracked_paths)
    with pytest.raises(RuntimeError, match="^stop-after-provenance$"):
        module.build_inventory(tmp_path)
