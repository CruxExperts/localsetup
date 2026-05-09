from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_ROOT))

import boss_ctl  # noqa: E402
from lib.boss_orchestrator.command import normalize_command  # noqa: E402
from lib.boss_orchestrator.state import StateStore  # noqa: E402


def test_command_argv_accepts_only_kilo_run() -> None:
    argv, error = normalize_command(
        ["kilo", "run", "--auto", "--agent", "sidekick", "summarize repo"]
    )

    assert error is None
    assert argv[:2] == ["kilo", "run"]


def test_command_string_is_rejected() -> None:
    argv, error = normalize_command("kilo run --auto 'summarize repo'")

    assert argv == []
    assert "command_argv YAML list" in str(error)


def test_command_argv_allows_literal_shell_like_text() -> None:
    argv, error = normalize_command(["kilo", "run", "--auto", "literal && text; ok"])

    assert error is None
    assert argv[-1] == "literal && text; ok"


def test_command_argv_rejects_non_allowlisted_executable() -> None:
    argv, error = normalize_command(["python3", "-c", "print('no')"])

    assert argv == []
    assert "kilo run" in str(error)


def test_finalize_refuses_failed_consensus(tmp_path, monkeypatch, capsys) -> None:
    store = StateStore(tmp_path)
    store.write_task({"id": "task-1", "status": "running"})
    store.write_consensus(
        "task-1",
        {
            "gate_passed": False,
            "requires_tiebreaker": False,
            "severity": "medium",
            "discrepancies": ["stdout mismatch"],
        },
    )
    monkeypatch.setattr(boss_ctl, "StateStore", lambda: store)

    rc = boss_ctl.cmd_finalize(argparse.Namespace(task_id="task-1"))

    assert rc == 2
    assert store.read_task("task-1")["status"] == "running"
    assert "gate did not pass" in capsys.readouterr().err


def test_finalize_refuses_tiebreaker_consensus(tmp_path, monkeypatch, capsys) -> None:
    store = StateStore(tmp_path)
    store.write_task({"id": "task-1", "status": "running"})
    store.write_consensus(
        "task-1",
        {
            "gate_passed": True,
            "requires_tiebreaker": True,
            "severity": "high",
            "discrepancies": ["status mismatch"],
        },
    )
    monkeypatch.setattr(boss_ctl, "StateStore", lambda: store)

    rc = boss_ctl.cmd_finalize(argparse.Namespace(task_id="task-1"))

    assert rc == 2
    assert store.read_task("task-1")["status"] == "running"
    assert "requires tiebreaker" in capsys.readouterr().err


def test_watchdog_reclaims_expired_lease_and_requeues_task(tmp_path) -> None:
    store = StateStore(tmp_path)
    store.write_task(
        {"id": "task-1", "status": "running", "attempts": 0, "max_attempts": 3}
    )
    store.claim_lease("task-1", "boss", ttl_seconds=1)
    lease_path = store.lease_path("task-1")
    lease = json.loads(lease_path.read_text(encoding="utf-8"))
    lease["start_ts"] = "2000-01-01T00:00:00+00:00"
    lease_path.write_text(json.dumps(lease), encoding="utf-8")

    reclaimed = store.reclaim_leases()

    assert reclaimed == {"orphan": 0, "expired": 1}
    assert not lease_path.exists()
    task = store.read_task("task-1")
    assert task["status"] == "pending"
    assert task["attempts"] == 1


def test_claim_lease_reclaims_existing_expired_lease(tmp_path) -> None:
    store = StateStore(tmp_path)
    store.claim_lease("task-1", "old-boss", ttl_seconds=1)
    lease_path = store.lease_path("task-1")
    lease = json.loads(lease_path.read_text(encoding="utf-8"))
    lease["start_ts"] = "2000-01-01T00:00:00+00:00"
    lease_path.write_text(json.dumps(lease), encoding="utf-8")

    assert store.claim_lease("task-1", "new-boss", ttl_seconds=60) is True
    assert store.read_lease("task-1")["worker_id"] == "new-boss"
