from __future__ import annotations

import ast
from collections import Counter
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback
import types
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "ls" / "skills" / "ls-agent-routing"
SCRIPT = SKILL / "scripts" / "agent_routing.py"
VALID_REQUEST = {
    "schema": "agent_routing_request_v1",
    "task_class": "routine",
    "risk": "low",
    "required_capabilities": [],
}


def run_select(request: dict[str, Any], *, script: Path = SCRIPT) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-I", str(script), "select", "--request", "-"],
        input=json.dumps(request),
        text=True,
        capture_output=True,
        env={"PYTHONPATH": ""},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def copied_skill(tmp_path: Path) -> Path:
    target = tmp_path / "isolated-skill"
    shutil.copytree(SKILL, target)
    return target


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def assert_resource_invalid(script: Path) -> None:
    receipt = run_select(VALID_REQUEST, script=script)
    assert receipt["status"] == "rejected"
    assert receipt["reason"] == "resource_invalid"
    assert "selected" not in receipt


def load_selector_module(script: Path):
    module_name = f"agent_routing_test_{hashlib.sha256(str(script).encode()).hexdigest()}"
    spec = importlib.util.spec_from_file_location(module_name, script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def run_loaded_select(module, monkeypatch, capsys) -> dict[str, Any]:
    monkeypatch.setattr(module.sys, "stdin", io.StringIO(json.dumps(VALID_REQUEST)))
    assert module.main(["select", "--request", "-"]) == 0
    return json.loads(capsys.readouterr().out)


def _install_replacement(target: Path, replacement: Path, *, directory: bool) -> None:
    if directory:
        replacement.mkdir()
    else:
        replacement.write_text('{"replacement":"outside"}', encoding="utf-8")
    replacement.rename(target)


STATIC_RESOURCE_ENTRIES = (
    (Path("schemas/routing-request.schema.json"), False),
    (Path("schemas/routing-receipt.schema.json"), False),
    (Path("resources/model-capability-matrix/manifest.json"), False),
    (Path("resources/model-capability-matrix/schema.json"), False),
    (Path("resources/model-capability-matrix/snapshot.json"), False),
    (Path("schemas"), True),
    (Path("resources"), True),
    (Path("resources/model-capability-matrix"), True),
)


def _fact_leaf_paths(value: Any, prefix: tuple[str | int, ...] = ()) -> list[tuple[str | int, ...]]:
    if isinstance(value, dict):
        return [path for key, item in value.items() for path in _fact_leaf_paths(item, (*prefix, key))]
    if isinstance(value, list):
        return [path for index, item in enumerate(value) for path in _fact_leaf_paths(item, (*prefix, index))]
    return [prefix]


def _replace_leaf(value: Any, path: tuple[str | int, ...]) -> None:
    cursor = value
    for part in path[:-1]:
        cursor = cursor[part]
    leaf = path[-1]
    old = cursor[leaf]
    if isinstance(old, str):
        cursor[leaf] = f"{old}-tampered"
    elif isinstance(old, bool):
        cursor[leaf] = not old
    elif isinstance(old, int):
        cursor[leaf] = old + 1
    elif isinstance(old, float):
        cursor[leaf] = old + 0.125
    else:  # every reviewed fact payload must remain JSON scalar at its leaf
        raise AssertionError(f"unsupported fact leaf {old!r}")


def test_select_uses_only_reviewed_static_candidate_and_omits_effort() -> None:
    receipt = run_select(VALID_REQUEST)

    assert receipt["schema"] == "agent_routing_receipt_v1"
    assert receipt["status"] == "selected"
    assert receipt["reason"] == "selected_static_reviewed"
    assert receipt["selection_policy"] == "static_reviewed_only"
    assert receipt["ultra_selected"] is False
    assert set(receipt["selected"]) == {"lane", "model"}
    assert receipt["selected"]["model"].startswith("gpt-5.6-")


def test_select_rejects_r00_raw_model_and_ultra_fields_without_processing() -> None:
    for key, value in (
        ("observation", {"model": "private"}),
        ("model", "gpt-5.6-sol"),
        ("allow_ultra", True),
        ("Ultra", True),
        ("prompt", "private"),
        ("endpoint", "https://private.invalid"),
    ):
        receipt = run_select({**VALID_REQUEST, key: value})
        assert receipt["status"] == "rejected"
        assert receipt["reason"] == "invalid_request"
        assert "selected" not in receipt


def test_select_does_not_promote_family_scoped_vision_to_a_concrete_candidate() -> None:
    receipt = run_select({**VALID_REQUEST, "required_capabilities": ["vision"]})

    assert receipt["status"] == "offline"
    assert receipt["reason"] == "candidate_evidence_unknown"
    assert "selected" not in receipt


def test_anchored_descriptors_reject_single_and_coordinated_tampering(tmp_path: Path) -> None:
    for relative in (
        Path("schemas/routing-request.schema.json"),
        Path("schemas/routing-receipt.schema.json"),
        Path("resources/model-capability-matrix/schema.json"),
    ):
        skill = copied_skill(tmp_path / relative.stem)
        target = skill / relative
        payload = load_json(target)
        payload["$id"] = "https://tampered.invalid/schema.json"
        write_json(target, payload)
        assert_resource_invalid(skill / "scripts" / "agent_routing.py")

    skill = copied_skill(tmp_path / "coordinated")
    schema = skill / "resources/model-capability-matrix/schema.json"
    manifest_path = skill / "resources/model-capability-matrix/manifest.json"
    payload = load_json(schema)
    payload["$id"] = "https://tampered.invalid/schema.json"
    write_json(schema, payload)
    manifest = load_json(manifest_path)
    manifest["matrix_schema_sha256"] = hashlib.sha256(schema.read_bytes()).hexdigest()
    write_json(manifest_path, manifest)
    assert_resource_invalid(skill / "scripts" / "agent_routing.py")


def test_anchored_evidence_tuples_and_every_reviewed_fact_leaf_reject_tampering(tmp_path: Path) -> None:
    base_manifest = load_json(SKILL / "resources/model-capability-matrix/manifest.json")
    for index, evidence in enumerate(base_manifest["evidence"]):
        for field in ("url", "access_date", "claim_scope"):
            skill = copied_skill(tmp_path / f"evidence-{index}-{field}")
            manifest_path = skill / "resources/model-capability-matrix/manifest.json"
            manifest = load_json(manifest_path)
            old = manifest["evidence"][index][field]
            manifest["evidence"][index][field] = (
                "https://tampered.invalid"
                if field == "url"
                else ("2000-01-01" if field == "access_date" else ("accounting" if old != "accounting" else "client_product"))
            )
            assert manifest["evidence"][index]["evidence_id"] == evidence["evidence_id"]
            assert manifest["evidence"][index][field] != old
            write_json(manifest_path, manifest)
            assert_resource_invalid(skill / "scripts" / "agent_routing.py")

    snapshot_path = SKILL / "resources/model-capability-matrix/snapshot.json"
    base_snapshot = load_json(snapshot_path)
    records = [*base_snapshot["model_records"], *base_snapshot["scoped_records"]]
    for record_index, record in enumerate(records):
        for leaf_path in _fact_leaf_paths(record["facts"]):
            skill = copied_skill(tmp_path / f"fact-{record_index}-{'-'.join(map(str, leaf_path))}")
            target_snapshot = skill / "resources/model-capability-matrix/snapshot.json"
            target_manifest = skill / "resources/model-capability-matrix/manifest.json"
            snapshot = load_json(target_snapshot)
            target_records = [*snapshot["model_records"], *snapshot["scoped_records"]]
            _replace_leaf(target_records[record_index]["facts"], leaf_path)
            write_json(target_snapshot, snapshot)
            manifest = load_json(target_manifest)
            manifest["snapshot_sha256"] = hashlib.sha256(target_snapshot.read_bytes()).hexdigest()
            write_json(target_manifest, manifest)
            assert_resource_invalid(skill / "scripts" / "agent_routing.py")


def test_snapshot_candidate_pattern_and_receipt_descriptor_tampering_never_select(tmp_path: Path) -> None:
    skill = copied_skill(tmp_path / "candidate")
    snapshot_path = skill / "resources/model-capability-matrix/snapshot.json"
    manifest_path = skill / "resources/model-capability-matrix/manifest.json"
    snapshot = load_json(snapshot_path)
    snapshot["candidates"][0]["model_id"] = "gpt-5.6-ultra"
    write_json(snapshot_path, snapshot)
    manifest = load_json(manifest_path)
    manifest["snapshot_sha256"] = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
    write_json(manifest_path, manifest)
    assert_resource_invalid(skill / "scripts" / "agent_routing.py")

    receipt_skill = copied_skill(tmp_path / "receipt")
    receipt_schema = receipt_skill / "schemas/routing-receipt.schema.json"
    receipt = load_json(receipt_schema)
    receipt["properties"]["selected"]["properties"]["model"]["pattern"] = ".*"
    write_json(receipt_schema, receipt)
    assert_resource_invalid(receipt_skill / "scripts" / "agent_routing.py")


@pytest.mark.parametrize(("relative", "directory"), STATIC_RESOURCE_ENTRIES)
@pytest.mark.parametrize("replacement_kind", ("symlink", "ordinary"))
def test_selector_rejects_preopen_static_resource_replacement_without_reading_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    relative: Path,
    directory: bool,
    replacement_kind: str,
) -> None:
    skill = copied_skill(tmp_path / f"preopen-{relative.name}-{replacement_kind}")
    target = skill / relative
    module = load_selector_module(skill / "scripts" / "agent_routing.py")
    original_open = module.os.open
    original_read = module.os.read
    backup = target.with_name(f"{target.name}.original")
    outside = target.with_name(f"{target.name}.outside")
    replacement_inode: int | None = None
    swapped = False

    def swapping_open(name, flags, mode=0o777, *, dir_fd=None):
        nonlocal replacement_inode, swapped
        is_target = name == target.name and bool(flags & module.os.O_DIRECTORY) is directory
        if not swapped and is_target:
            swapped = True
            target.rename(backup)
            if replacement_kind == "symlink":
                if directory:
                    outside.mkdir()
                    target.symlink_to(outside, target_is_directory=True)
                else:
                    outside.write_text('{"outside":"replacement"}', encoding="utf-8")
                    target.symlink_to(outside)
                replacement_inode = os.stat(outside).st_ino
            else:
                _install_replacement(target, outside, directory=directory)
                replacement_inode = os.stat(target).st_ino
        return original_open(name, flags, mode, dir_fd=dir_fd)

    def guarded_read(fd, size):
        assert replacement_inode is None or os.fstat(fd).st_ino != replacement_inode
        return original_read(fd, size)

    monkeypatch.setattr(module.os, "open", swapping_open)
    monkeypatch.setattr(module.os, "read", guarded_read)
    receipt = run_loaded_select(module, monkeypatch, capsys)
    assert swapped
    assert receipt["status"] == "rejected"
    assert receipt["reason"] == "resource_invalid"
    assert "selected" not in receipt
    assert str(target) not in json.dumps(receipt)
    assert str(outside) not in json.dumps(receipt)


@pytest.mark.parametrize(("relative", "directory"), STATIC_RESOURCE_ENTRIES)
@pytest.mark.parametrize("replacement_kind", ("symlink", "ordinary"))
def test_selector_keeps_held_static_resource_fd_after_postopen_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    relative: Path,
    directory: bool,
    replacement_kind: str,
) -> None:
    skill = copied_skill(tmp_path / f"postopen-{relative.name}-{replacement_kind}")
    target = skill / relative
    module = load_selector_module(skill / "scripts" / "agent_routing.py")
    original_open = module.os.open
    original_read = module.os.read
    backup = target.with_name(f"{target.name}.original")
    outside = target.with_name(f"{target.name}.outside")
    original_inode = target.stat().st_ino
    replacement_inode: int | None = None
    held_target_fd: int | None = None
    target_read_seen = False
    swapped = False

    def swapping_open(name, flags, mode=0o777, *, dir_fd=None):
        nonlocal held_target_fd, replacement_inode, swapped
        fd = original_open(name, flags, mode, dir_fd=dir_fd)
        is_target = name == target.name and bool(flags & module.os.O_DIRECTORY) is directory
        if not swapped and is_target:
            swapped = True
            held_target_fd = fd
            target.rename(backup)
            if replacement_kind == "symlink":
                if directory:
                    outside.mkdir()
                    target.symlink_to(outside, target_is_directory=True)
                else:
                    outside.write_text('{"outside":"replacement"}', encoding="utf-8")
                    target.symlink_to(outside)
                replacement_inode = os.stat(outside).st_ino
            else:
                _install_replacement(target, outside, directory=directory)
                replacement_inode = os.stat(target).st_ino
        return fd

    def guarded_read(fd, size):
        nonlocal target_read_seen
        inode = os.fstat(fd).st_ino
        assert inode != replacement_inode
        if fd == held_target_fd and not directory and inode == original_inode:
            target_read_seen = True
        return original_read(fd, size)

    monkeypatch.setattr(module.os, "open", swapping_open)
    monkeypatch.setattr(module.os, "read", guarded_read)
    receipt = run_loaded_select(module, monkeypatch, capsys)
    assert swapped
    assert directory or target_read_seen
    assert receipt["status"] == "selected"
    assert receipt["reason"] == "selected_static_reviewed"


def test_selector_static_reader_rejects_invalid_component_and_bounds_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill = copied_skill(tmp_path / "reader")
    module = load_selector_module(skill / "scripts" / "agent_routing.py")
    root_fd = os.open(skill / "schemas", os.O_RDONLY | os.O_DIRECTORY)
    original_read = module.os.read
    original_close = module.os.close
    closed: list[int] = []
    try:
        with pytest.raises(module.RoutingError) as malformed:
            module._read_file(root_fd, "\x00")
        assert str(skill) not in str(malformed.value)

        overflow = skill / "schemas" / "overflow.json"
        overflow.write_bytes(b"x" * 5)
        monkeypatch.setattr(module, "MAX_STATIC_RESOURCE_BYTES", 4)
        monkeypatch.setattr(module.os, "read", lambda fd, size: pytest.fail("overflow target was read"))
        with pytest.raises(module.RoutingError):
            module._read_file(root_fd, "overflow.json")

        chunked = skill / "schemas" / "chunked.json"
        chunked.write_bytes(b"payload")
        monkeypatch.setattr(module, "MAX_STATIC_RESOURCE_BYTES", 32)
        monkeypatch.setattr(module.os, "read", lambda fd, size: original_read(fd, min(size, 2)))
        monkeypatch.setattr(module.os, "close", lambda fd: (closed.append(fd), original_close(fd))[1])
        assert module._read_file(root_fd, "chunked.json") == b"payload"
        assert closed

        monkeypatch.setattr(module.os, "read", lambda fd, size: b"")
        with pytest.raises(module.RoutingError):
            module._read_file(root_fd, "chunked.json")

        monkeypatch.setattr(module.os, "read", lambda fd, size: b"x" if size == 1 else original_read(fd, size))
        with pytest.raises(module.RoutingError):
            module._read_file(root_fd, "chunked.json")
    finally:
        os.close(root_fd)


@pytest.mark.parametrize("failure_name", (None, "routing-request.schema.json"))
def test_selector_closes_every_static_descriptor_on_success_and_open_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_name: str | None,
) -> None:
    skill = copied_skill(tmp_path / f"descriptor-trace-{failure_name or 'success'}")
    module = load_selector_module(skill / "scripts" / "agent_routing.py")
    original_open = module.os.open
    original_close = module.os.close
    opened: list[int] = []
    closed: list[int] = []

    def tracing_open(name, flags, mode=0o777, *, dir_fd=None):
        if name == failure_name:
            raise OSError("injected open failure")
        fd = original_open(name, flags, mode, dir_fd=dir_fd)
        opened.append(fd)
        return fd

    def tracing_close(fd):
        closed.append(fd)
        return original_close(fd)

    monkeypatch.setattr(module.os, "open", tracing_open)
    monkeypatch.setattr(module.os, "close", tracing_close)
    snapshot, _, reason = module._load_snapshot()
    if failure_name is None:
        assert snapshot and reason is None
    else:
        assert snapshot == {} and reason == "resource_invalid"
    assert set(opened) <= set(closed)


def _install_selector_descriptor_failure(module, monkeypatch: pytest.MonkeyPatch, capability: str, sentinel: str) -> None:
    original_os = module.os
    proxy = types.SimpleNamespace(
        stat=original_os.stat,
        open=original_os.open,
        fstat=original_os.fstat,
        read=original_os.read,
        close=original_os.close,
        O_RDONLY=original_os.O_RDONLY,
        O_DIRECTORY=original_os.O_DIRECTORY,
        O_NOFOLLOW=original_os.O_NOFOLLOW,
    )
    monkeypatch.setattr(module, "os", proxy)
    original_stat = proxy.stat
    original_open = proxy.open
    original_fstat = proxy.fstat
    original_read = proxy.read
    original_close = proxy.close
    if capability == "stat":
        monkeypatch.setattr(proxy, "stat", lambda *args, **kwargs: (_ for _ in ()).throw(NotImplementedError(sentinel)))
    elif capability == "open":
        monkeypatch.setattr(proxy, "open", lambda *args, **kwargs: (_ for _ in ()).throw(NotImplementedError(sentinel)))
    elif capability == "fstat":
        def failing_fstat(fd):
            original_fstat(fd)
            raise NotImplementedError(sentinel)

        monkeypatch.setattr(proxy, "fstat", failing_fstat)
    elif capability == "read":
        monkeypatch.setattr(proxy, "read", lambda *args, **kwargs: (_ for _ in ()).throw(NotImplementedError(sentinel)))
    elif capability == "close":
        read_started = False

        def marking_read(fd, size):
            nonlocal read_started
            read_started = True
            return original_read(fd, size)

        def failing_close(fd):
            if read_started:
                raise NotImplementedError(sentinel)
            return original_close(fd)

        monkeypatch.setattr(proxy, "read", marking_read)
        monkeypatch.setattr(proxy, "close", failing_close)
    elif capability == "O_NOFOLLOW":
        monkeypatch.delattr(proxy, "O_NOFOLLOW", raising=False)
    elif capability == "O_DIRECTORY":
        monkeypatch.delattr(proxy, "O_DIRECTORY", raising=False)
    else:  # pragma: no cover - parameter contract
        raise AssertionError(capability)
    assert original_stat and original_open  # retain explicit real-operation bindings for the test matrix


@pytest.mark.parametrize("capability", ("stat", "open", "fstat", "read", "close", "O_NOFOLLOW", "O_DIRECTORY"))
def test_selector_normalizes_every_descriptor_capability_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    capability: str,
) -> None:
    skill = copied_skill(tmp_path / f"descriptor-{capability}")
    module = load_selector_module(skill / "scripts" / "agent_routing.py")
    sentinel = f"selector-private-{capability}"
    _install_selector_descriptor_failure(module, monkeypatch, capability, sentinel)
    assert module._load_snapshot() == ({}, "0" * 64, "resource_invalid")
    receipt = run_loaded_select(module, monkeypatch, capsys)
    assert receipt["status"] == "rejected"
    assert receipt["reason"] == "resource_invalid"
    assert sentinel not in json.dumps(receipt)
    assert str(skill) not in json.dumps(receipt)


def test_selector_root_fstat_failure_closes_every_opened_descriptor_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill = copied_skill(tmp_path / "root-fstat")
    module = load_selector_module(skill / "scripts" / "agent_routing.py")
    original_os = module.os
    proxy = types.SimpleNamespace(
        open=original_os.open,
        fstat=original_os.fstat,
        close=original_os.close,
        stat=original_os.stat,
        read=original_os.read,
        O_RDONLY=original_os.O_RDONLY,
        O_DIRECTORY=original_os.O_DIRECTORY,
        O_NOFOLLOW=original_os.O_NOFOLLOW,
    )
    monkeypatch.setattr(module, "os", proxy)
    original_open = proxy.open
    original_fstat = proxy.fstat
    original_close = proxy.close
    opened: list[int] = []
    closed: list[int] = []

    def tracing_open(name, flags, mode=0o777, *, dir_fd=None):
        fd = original_open(name, flags, mode, dir_fd=dir_fd)
        opened.append(fd)
        return fd

    def failing_fstat(fd):
        original_fstat(fd)
        raise NotImplementedError("selector-root-fstat-private")

    def tracing_close(fd):
        closed.append(fd)
        return original_close(fd)

    monkeypatch.setattr(proxy, "open", tracing_open)
    monkeypatch.setattr(proxy, "fstat", failing_fstat)
    monkeypatch.setattr(proxy, "close", tracing_close)
    assert module._load_snapshot() == ({}, "0" * 64, "resource_invalid")
    assert Counter(opened) == Counter(closed)


def test_selector_source_has_no_runtime_or_process_ingress() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imports = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    assert not imports.intersection({"socket", "subprocess", "ctypes", "urllib", "requests"})
    assert {"os", "stat"} <= imports
    os_attributes = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "os"
    }
    assert os_attributes <= {"open", "stat", "fstat", "read", "close", "O_RDONLY", "O_DIRECTORY", "O_NOFOLLOW"}
    stat_attributes = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "stat"
    }
    assert stat_attributes <= {"S_ISDIR", "S_ISREG"}
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("Popen(", "os.system", "worker", "account probe", "R00"):
        assert forbidden not in source
