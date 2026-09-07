import hashlib

import pytest

from ls.core.agent import heartbeat_budget_store as store
from ls.tests.test_heartbeat_budget import reserve, reviewed
from ls.tests.test_heartbeat_budget_store import initialize
from ls.tests.test_heartbeat_accounting_cli import call, private


def amendment(root, operation="two"):
    return dict(type="authorize", operation=operation,
                policy_sha256=hashlib.sha256((root/store.POLICY).read_bytes()).hexdigest(),
                authorization=dict(binding="f"*64, run=reserve()["run"], compact=None))


def settled(root, workspace, state, operation="one", decision="no_progress", binding="e"*64):
    state = store.append(root, workspace, reserve(operation), state["head"], binding=binding)
    for event in reviewed(operation, decision):
        state = store.append(root, workspace, event, state["head"])
    return state


def test_public_amendment_preserves_budget_policy_and_streak(tmp_path):
    root, workspace, state = initialize(tmp_path)
    state = settled(root, workspace, state)
    original = {p.name: p.read_bytes() for p in root.iterdir()}
    event = amendment(root)
    source = private(tmp_path/"authorization.json", {k: v for k, v in event.items() if k != "type"})
    added = call(workspace, "accounting", "authorize", "--accounting-root", root,
                 "--input", source, "--expected-head", state["head"])
    assert added["summary"] == state["summary"]
    assert added["policy"] == state["policy"]
    assert all((root/name).read_bytes() == raw for name, raw in original.items())
    assert store.inspect(root, workspace) == {k: v for k, v in added.items() if k != "schema_version"}
    state = settled(root, workspace, added, "two", binding="f"*64)
    assert state["summary"]["status"] == "no_progress_stop"
    assert state["summary"]["charged"]["requests"] == 4
    with pytest.raises(ValueError, match="stopped"):
        store.append(root, workspace, amendment(root, "three"), state["head"])


@pytest.mark.parametrize("problem", ["duplicate", "policy", "head", "pending", "accepted", "binding"])
def test_invalid_amendment_is_nonmutating(tmp_path, problem):
    root, workspace, state = initialize(tmp_path)
    event = amendment(root)
    if problem == "duplicate":
        event["operation"] = "one"
    elif problem == "policy":
        event["policy_sha256"] = "0"*64
    elif problem == "pending":
        state = store.append(root, workspace, reserve(), state["head"], binding="e"*64)
    elif problem == "accepted":
        state = settled(root, workspace, state, decision="accepted")
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    with pytest.raises(ValueError):
        store.append(root, workspace, event, "0"*64 if problem == "head" else state["head"],
                     binding="f"*64 if problem == "binding" else None)
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before


def test_added_binding_and_replay_remain_enforced(tmp_path):
    root, workspace, state = initialize(tmp_path)
    state = store.append(root, workspace, amendment(root), state["head"])
    with pytest.raises(ValueError, match="authorization"):
        store.append(root, workspace, reserve("two"), state["head"], binding="e"*64)
    state = settled(root, workspace, state, "two", "progress", "f"*64)
    with pytest.raises(ValueError, match="replayed"):
        store.append(root, workspace, reserve("two"), state["head"], binding="f"*64)
    with pytest.raises(ValueError, match="already exists"):
        store.append(root, workspace, amendment(root), state["head"])


def test_replay_rejects_future_grant_and_inventory_overflow(tmp_path):
    from ls.core.agent import heartbeat_authorization as authority
    from ls.tests.test_heartbeat_budget_store import document
    root, workspace, _ = initialize(tmp_path)
    value = document(workspace)
    event = amendment(root)
    with pytest.raises(ValueError, match="differs"):
        authority.replay(value, [reserve("two"), event])
    events = [{**event, "operation": f"op-{n}"} for n in range(256)]
    grants, summary = authority.replay(value, events[:255])
    assert len(grants) == 256 and summary["charged"]["attempts"] == 0
    with pytest.raises(ValueError, match="inventory is full"):
        authority.replay(value, events)
    with pytest.raises(ValueError, match="record limit"):
        authority.replay(value, [event]*3073)


def test_amendment_cannot_replenish_exhausted_budget(tmp_path):
    root, workspace, state = initialize(tmp_path)
    for n in range(4):
        event = amendment(root, f"attempt-{n}")
        state = store.append(root, workspace, event, state["head"])
        state = settled(root, workspace, state, event["operation"], "progress", "f"*64)
    event = amendment(root, "exhausted")
    state = store.append(root, workspace, event, state["head"])
    with pytest.raises(ValueError, match="exhausted"):
        store.append(root, workspace, reserve("exhausted"), state["head"], binding="f"*64)
    assert store.inspect(root, workspace)["summary"]["charged"]["attempts"] == 4
