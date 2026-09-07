import hashlib

import pytest

from ls.core.agent import heartbeat_budget_store as store
from ls.tests.test_heartbeat_budget import policy, reserve, reviewed


def document(workspace):
    event = reserve()
    return dict(schema_version=1, workspace=str(workspace), policy=policy(),
                authorizations={"one": dict(binding="e"*64, run=event["run"], compact=None)})


def initialize(tmp_path):
    root, workspace = tmp_path/"control", tmp_path/"workspace"
    workspace.mkdir()
    value = document(workspace)
    state = store.initialize(root, workspace, value, hashlib.sha256(store.files.encode(value)).hexdigest())
    return root, workspace, state


def test_durable_reservation_review_and_replay(tmp_path):
    root, workspace, state = initialize(tmp_path)
    state = store.append(root, workspace, reserve(), state["head"], binding="e"*64)
    assert store.inspect(root, workspace)["summary"]["status"] == "reconciliation_required"
    for event in reviewed("one", "no_progress"):
        state = store.append(root, workspace, event, state["head"])
    assert state["summary"]["consecutive_no_progress"] == 1
    assert state["summary"]["charged"]["tokens"] == 100
    with pytest.raises(ValueError, match="replayed"):
        store.append(root, workspace, reserve(), state["head"], binding="e"*64)


def test_binding_and_stale_head_refused_without_write(tmp_path):
    root, workspace, state = initialize(tmp_path)
    before = set(root.iterdir())
    with pytest.raises(ValueError, match="authorization"):
        store.append(root, workspace, reserve(), state["head"], binding="f"*64)
    assert set(root.iterdir()) == before
    store.append(root, workspace, reserve(), state["head"], binding="e"*64)
    with pytest.raises(ValueError, match="changed"):
        store.append(root, workspace, reserve(), state["head"], binding="e"*64)


def test_uncertain_publish_preserves_reservation(tmp_path, monkeypatch):
    root, workspace, state = initialize(tmp_path)
    original = store.files._publish
    def uncertain(*args):
        original(*args)
        raise OSError("lost acknowledgement")
    monkeypatch.setattr(store.files, "_publish", uncertain)
    with pytest.raises(OSError):
        store.append(root, workspace, reserve(), state["head"], binding="e"*64)
    observed = store.inspect(root, workspace)
    assert observed["summary"]["status"] == "reconciliation_required"
    assert observed["summary"]["charged"]["requests"] == 2
    with pytest.raises(ValueError, match="changed"):
        store.append(root, workspace, reserve(), state["head"], binding="e"*64)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "mode", "extra", "tamper"])
def test_unsafe_or_changed_state_refused(tmp_path, kind):
    root, workspace, _ = initialize(tmp_path)
    path = root/store.POLICY
    if kind == "symlink":
        original = tmp_path/"original"
        path.rename(original)
        path.symlink_to(original)
    elif kind == "hardlink":
        import os
        os.link(path, tmp_path/"linked")
    elif kind == "mode":
        path.chmod(0o644)
    elif kind == "extra":
        (root/"unexpected").write_text("custom")
    else:
        path.write_bytes(path.read_bytes()+b" ")
    with pytest.raises((ValueError, OSError)):
        store.inspect(root, workspace)


def test_missing_read_and_workspace_overlap_never_create(tmp_path):
    root, workspace = tmp_path/"absent", tmp_path/"workspace"
    with pytest.raises(FileNotFoundError):
        store.inspect(root, workspace)
    assert not root.exists()
    value = document(workspace)
    with pytest.raises(ValueError, match="separate"):
        store.initialize(workspace/"control", workspace, value,
                         hashlib.sha256(store.files.encode(value)).hexdigest())
    assert not workspace.exists()


def test_append_does_not_recreate_missing_lease(tmp_path):
    root, workspace, state = initialize(tmp_path)
    (root/store.LOCK_NAME).unlink()
    with pytest.raises(FileNotFoundError, match="lease"):
        store.append(root, workspace, reserve(), state["head"], binding="e"*64)
    assert not (root/store.LOCK_NAME).exists()


def test_inventory_stops_at_bounded_entry_count(monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    consumed = []
    def entries():
        for n in range(4000):
            consumed.append(n)
            yield SimpleNamespace(name=str(n))
    @contextmanager
    def scan(_):
        yield entries()
    monkeypatch.setattr(store.os, "scandir", scan)
    with pytest.raises(ValueError, match="inventory exceeds"):
        store._names(0)
    assert len(consumed) == 3075
