import copy

import pytest

from ls.core.agent import heartbeat_budget as budget


def policy():
    return {"schema_version": 1, "task": "task", "revision": "a"*64, "criterion": "b"*64,
            "budget": dict(attempts=4, requests=10, tools=20, tokens=1000, seconds=100, compactions=2),
            "no_progress_limit": 2}


def reserve(operation="one", compact=None):
    return dict(type="reserve", operation=operation,
                run=dict(requests=2, tools=3, tokens=100, seconds=10), compact=compact)


def reviewed(operation, decision):
    return [dict(type="result", operation=operation, result="c"*64),
            dict(type="review", operation=operation, result="c"*64, decision=decision,
                 evidence="d"*64, rationale="Checked the bound acceptance criterion")]


def test_compound_reservation_counts_both_phases_before_dispatch():
    records = [reserve(compact=dict(tokens=200, seconds=20))]
    result = budget.summarize(policy(), records)
    assert result["charged"] == dict(attempts=1, requests=3, tools=3, tokens=300, seconds=30, compactions=1)
    assert result["status"] == "reconciliation_required"


@pytest.mark.parametrize("dimension", sorted(budget.DIMENSIONS))
def test_compound_exhaustion_is_atomic(dimension):
    p = policy()
    allocation = budget.envelope(reserve()["run"], dict(tokens=200, seconds=20))
    p["budget"][dimension] = allocation[dimension]-1
    # Keep the policy valid when testing the attempts cap.
    if dimension == "attempts":
        records = [reserve(), *reviewed("one", "progress")]
        p["budget"]["attempts"] = 1
        p["no_progress_limit"] = 1
        event = reserve("two", dict(tokens=200, seconds=20))
    else:
        records, event = [], reserve(compact=dict(tokens=200, seconds=20))
    before = copy.deepcopy(records)
    with pytest.raises(ValueError, match="exhausted"):
        budget.append(p, records, event)
    assert records == before


def test_result_alone_is_not_progress_and_review_cannot_refund():
    records = [reserve(), dict(type="result", operation="one", result="c"*64)]
    assert budget.summarize(policy(), records)["status"] == "awaiting_controller_review"
    with pytest.raises(ValueError):
        budget.append(policy(), records, reserve("two"))
    records += [reviewed("one", "progress")[1]]
    after = budget.summarize(policy(), records)
    assert after["status"] == "ready" and after["charged"]["tokens"] == 100


def test_no_progress_stops_new_identity_and_compaction():
    records = [reserve(), *reviewed("one", "no_progress"),
               reserve("new-session", dict(tokens=100, seconds=10)), *reviewed("new-session", "no_progress")]
    assert budget.summarize(policy(), records)["status"] == "no_progress_stop"
    with pytest.raises(ValueError, match="stopped"):
        budget.append(policy(), records, reserve("third"))


def test_reviewed_progress_resets_streak_but_not_total_budget():
    records = [reserve(), *reviewed("one", "no_progress"),
               reserve("two"), *reviewed("two", "progress")]
    report = budget.summarize(policy(), records)
    assert report["consecutive_no_progress"] == 0 and report["charged"]["attempts"] == 2


def test_replay_wrong_review_and_accepted_task_refused():
    records = [reserve(), *reviewed("one", "accepted")]
    assert budget.summarize(policy(), records)["status"] == "accepted"
    with pytest.raises(ValueError):
        budget.append(policy(), records, reserve("two"))
    records = [reserve(), *reviewed("one", "progress")]
    with pytest.raises(ValueError, match="replayed"):
        budget.append(policy(), records, reserve())
    records[-1]["result"] = "e"*64
    with pytest.raises(ValueError, match="bind"):
        budget.summarize(policy(), records)


@pytest.mark.parametrize("bad", [True, 1.5, -1, "1"])
def test_limits_are_strict_integers(bad):
    event = reserve()
    event["run"]["requests"] = bad
    with pytest.raises(ValueError):
        budget.summarize(policy(), [event])
