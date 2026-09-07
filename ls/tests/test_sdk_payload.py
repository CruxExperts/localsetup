from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from ls.core.sdk_payload.integrity import verify

ROOT = Path(__file__).resolve().parents[2]


def test_canonical_payload_is_complete_and_does_not_import_sdk():
    import sys

    before = {name for name in sys.modules if name.startswith("pydantic_ai") or name.startswith("pydantic_graph")}
    manifest = verify(ROOT / "vendor/lscli")
    assert len([e for e in manifest["files"].values() if e["role"] == "runtime"]) == 564
    assert len(manifest["patches"]) == 1
    assert {name for name in sys.modules if name.startswith("pydantic_ai") or name.startswith("pydantic_graph")} == before


@pytest.fixture
def payload(tmp_path):
    original = json.loads((ROOT / "vendor/lscli/manifest.json").read_text())
    manifest = copy.deepcopy(original)
    manifest["files"] = {}
    manifest["patches"] = []
    for component in manifest["components"]:
        for name, role in [(component["namespace"] + "/__init__.py", "runtime"), (component["license_file"], "license")]:
            data = b"fixture\n"
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            entry = {"component": component["name"], "role": role, "sha256": hashlib.sha256(data).hexdigest()}
            if role == "runtime":
                entry["upstream_sha256"] = entry["sha256"]
            manifest["files"][name] = entry
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    assert verify(tmp_path)
    return tmp_path, manifest


@pytest.mark.parametrize("mutation", ["changed", "missing", "extra", "symlink", "directory_link", "unsafe", "license", "unrecorded_patch", "owner"])
def test_rejects_payload_tampering(payload, mutation):
    root, manifest = payload
    target = root / "pydantic_ai/__init__.py"
    if mutation == "changed":
        target.write_text("changed")
    elif mutation == "missing":
        target.unlink()
    elif mutation == "extra":
        (root / "extra.py").write_text("pass")
    elif mutation == "symlink":
        target.unlink()
        target.symlink_to(root / "licenses/pydantic-ai-slim.txt")
    elif mutation == "directory_link":
        (root / "alias").symlink_to(root / "pydantic_ai", target_is_directory=True)
    elif mutation == "unsafe":
        manifest["files"]["../escape.py"] = manifest["files"].pop("pydantic_ai/__init__.py")
    elif mutation == "license":
        manifest["components"][0]["license_file"] = "pydantic_ai/__init__.py"
    elif mutation == "unrecorded_patch":
        manifest["files"]["pydantic_ai/__init__.py"]["upstream_sha256"] = "0" * 64
    elif mutation == "owner":
        manifest["files"]["pydantic_ai/__init__.py"]["component"] = "pydantic-graph"
    (root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        verify(root)


@pytest.mark.parametrize("field", ["version", "commit", "sdist", "source_archive_url"])
def test_rejects_incomplete_provenance(payload, field):
    root, manifest = payload
    del manifest["components"][0][field]
    (root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        verify(root)


def test_rejects_unreadable_subtree(payload, monkeypatch):
    import os

    root, _ = payload
    (root / "unreadable").mkdir()
    original = os.scandir

    def scandir(path):
        if Path(path).name == "unreadable":
            raise PermissionError("cannot enumerate payload subtree")
        return original(path)

    monkeypatch.setattr(os, "scandir", scandir)
    with pytest.raises(PermissionError):
        verify(root)
