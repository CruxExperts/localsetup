from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_ROOT))

import boss_ctl  # noqa: E402
from lib.boss_orchestrator.command import normalize_command  # noqa: E402
from lib.boss_orchestrator.state import (  # noqa: E402
    MAX_PATH_ID_LEN,
    StateStore,
    validate_path_id,
)


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

    assert reclaimed == {"invalid": 0, "orphan": 0, "expired": 1}
    assert not lease_path.exists()
    task = store.read_task("task-1")
    assert task["status"] == "pending"
    assert task["attempts"] == 1


def test_watchdog_quarantines_invalid_lease_and_reclaims_valid_expired_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store = StateStore(tmp_path / "state")
    store.write_task(
        {"id": "task-1", "status": "running", "attempts": 0, "max_attempts": 3}
    )
    store.claim_lease("task-1", "boss", ttl_seconds=1)
    lease_path = store.lease_path("task-1")
    lease = json.loads(lease_path.read_text(encoding="utf-8"))
    lease["start_ts"] = "2000-01-01T00:00:00+00:00"
    lease_path.write_text(json.dumps(lease), encoding="utf-8")
    poison_lease = store.root / "leases" / "bad..id.lock"
    poison_lease.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(boss_ctl, "StateStore", lambda: store)

    rc = boss_ctl.cmd_watchdog(argparse.Namespace())

    assert rc == 0
    assert "1 invalid lease(s)" in capsys.readouterr().out
    assert not poison_lease.exists()
    quarantine_files = list((store.root / "deadlettered_leases").glob("*.lock"))
    assert len(quarantine_files) == 1
    assert store.read_task("task-1")["status"] == "pending"
    assert not lease_path.exists()


def test_claim_lease_reclaims_existing_expired_lease(tmp_path) -> None:
    store = StateStore(tmp_path)
    store.claim_lease("task-1", "old-boss", ttl_seconds=1)
    lease_path = store.lease_path("task-1")
    lease = json.loads(lease_path.read_text(encoding="utf-8"))
    lease["start_ts"] = "2000-01-01T00:00:00+00:00"
    lease_path.write_text(json.dumps(lease), encoding="utf-8")

    assert store.claim_lease("task-1", "new-boss", ttl_seconds=60) is True
    assert store.read_lease("task-1")["worker_id"] == "new-boss"


@pytest.mark.parametrize(
    "bad_id",
    ["../escape", "a/b", "", "bad\x1fcontrol"],
)
def test_validate_path_id_rejects_invalid_values(bad_id: str) -> None:
    with pytest.raises(ValueError):
        validate_path_id(bad_id, field_name="task_id")


def test_validate_path_id_rejects_non_string() -> None:
    with pytest.raises(ValueError):
        validate_path_id(42, field_name="task_id")


def test_validate_path_id_rejects_overlong_value() -> None:
    with pytest.raises(ValueError, match=f"at most {MAX_PATH_ID_LEN} characters"):
        validate_path_id("a" * (MAX_PATH_ID_LEN + 1), field_name="task_id")


@pytest.mark.parametrize(
    "bad_task_id",
    ["../escape", "a/b", "", "bad\x1fcontrol", "a" * (MAX_PATH_ID_LEN + 1)],
)
def test_state_store_path_helpers_reject_invalid_ids(
    tmp_path: Path, bad_task_id: str
) -> None:
    store = StateStore(tmp_path)
    with pytest.raises(ValueError):
        store.task_path(bad_task_id)
    with pytest.raises(ValueError):
        store.result_path(bad_task_id)
    with pytest.raises(ValueError):
        store.lease_path(bad_task_id)
    with pytest.raises(ValueError):
        store.consensus_path(bad_task_id)
    with pytest.raises(ValueError):
        store.session_path(bad_task_id)


def test_state_store_heartbeat_path_rejects_invalid_worker_id(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    with pytest.raises(ValueError):
        store.heartbeat_path("../escape")


def test_state_store_enqueue_rejects_overlong_id_before_queue_write(tmp_path: Path) -> None:
    store = StateStore(tmp_path)

    with pytest.raises(ValueError):
        store.enqueue({"id": "a" * (MAX_PATH_ID_LEN + 1), "status": "pending"})

    assert not store.queue_file.exists()


def test_cmd_enqueue_rejects_invalid_session_id_before_queue_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    task_file = tmp_path / "task.yaml"
    task_file.write_text(
        "\n".join(
            [
                "id: task1",
                "session_id: ../bad",
                "command_argv:",
                "  - kilo",
                "  - run",
                "  - --auto",
                "  - noop",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="session_id"):
        boss_ctl.cmd_enqueue(argparse.Namespace(task_file=str(task_file)))

    state_root = tmp_path / ".kilo/state/orchestrator"
    assert not (state_root / "queue.jsonl").exists()
    assert list((state_root / "tasks").glob("*.json")) == []


@pytest.mark.parametrize(
    ("field_name", "error_field"),
    [
        ("id", "task_id"),
        ("session_id", "session_id"),
        ("worker_primary", "worker_primary"),
        ("worker_verifier", "worker_verifier"),
    ],
)
def test_cmd_enqueue_rejects_overlong_ids_before_queue_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field_name: str,
    error_field: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    task_file = tmp_path / "task.yaml"
    task_file.write_text(
        "\n".join(
            [
                "id: task1",
                "session_id: session1",
                "worker_primary: worker-primary",
                "worker_verifier: worker-verifier",
                f"{field_name}: {'a' * (MAX_PATH_ID_LEN + 1)}",
                "command_argv:",
                "  - kilo",
                "  - run",
                "  - --auto",
                "  - noop",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=error_field):
        boss_ctl.cmd_enqueue(argparse.Namespace(task_file=str(task_file)))

    state_root = tmp_path / ".kilo/state/orchestrator"
    assert not (state_root / "queue.jsonl").exists()
    assert list((state_root / "tasks").glob("*.json")) == []


def test_cmd_enqueue_rejects_boundary_task_id_before_queue_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    task_file = tmp_path / "task.yaml"
    task_file.write_text(
        "\n".join(
            [
                f"id: {'a' * MAX_PATH_ID_LEN}",
                "session_id: session1",
                "worker_primary: worker-primary",
                "worker_verifier: worker-verifier",
                "command_argv:",
                "  - kilo",
                "  - run",
                "  - --auto",
                "  - noop",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="primary_task_id"):
        boss_ctl.cmd_enqueue(argparse.Namespace(task_file=str(task_file)))

    state_root = tmp_path / ".kilo/state/orchestrator"
    assert not (state_root / "queue.jsonl").exists()
    assert list((state_root / "tasks").glob("*.json")) == []


def test_cmd_dispatch_rejects_invalid_session_id_before_mutating_running_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store = StateStore(tmp_path / "state")
    store.write_task(
        {
            "id": "task1",
            "status": "pending",
            "session_id": "../bad",
            "command_argv": ["kilo", "run", "--auto", "noop"],
            "worker_primary": "worker-primary",
            "worker_verifier": "worker-verifier",
        }
    )
    monkeypatch.setattr(boss_ctl, "StateStore", lambda: store)

    rc = boss_ctl.cmd_dispatch(argparse.Namespace(max_dispatch=1))

    assert rc == 2
    assert "invalid task metadata" in capsys.readouterr().err
    assert store.read_task("task1")["status"] == "failed"
    assert store.read_task("task1-primary") is None
    assert store.read_task("task1-verifier") is None
    assert not store.lease_path("task1").exists()
    assert list((store.root / "sessions").glob("*.json")) == []
    assert store.deadletter_file.exists()


def test_cmd_dispatch_rejects_boundary_task_id_before_leasing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store = StateStore(tmp_path / "state")
    task_id = "a" * MAX_PATH_ID_LEN
    store.write_task(
        {
            "id": task_id,
            "status": "pending",
            "session_id": "session1",
            "command_argv": ["kilo", "run", "--auto", "noop"],
            "worker_primary": "worker-primary",
            "worker_verifier": "worker-verifier",
        }
    )
    monkeypatch.setattr(boss_ctl, "StateStore", lambda: store)

    rc = boss_ctl.cmd_dispatch(argparse.Namespace(max_dispatch=1))

    assert rc == 2
    assert "primary_task_id" in capsys.readouterr().err
    assert store.read_task(task_id)["status"] == "pending"
    assert list((store.root / "tasks").glob(f"{task_id}-*.json")) == []
    assert not store.lease_path(task_id).exists()
    assert list((store.root / "sessions").glob("*.json")) == []
    assert not store.deadletter_file.exists()


def test_cmd_dispatch_quarantines_invalid_task_filename_without_leasing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store = StateStore(tmp_path / "state")
    poison_file = store.root / "tasks" / "bad..id.json"
    poison_file.write_text(
        json.dumps({"status": "pending", "command_argv": ["kilo", "run", "noop"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(boss_ctl, "StateStore", lambda: store)

    rc = boss_ctl.cmd_dispatch(argparse.Namespace(max_dispatch=1))

    assert rc == 0
    assert "quarantined invalid task file" in capsys.readouterr().err
    assert not poison_file.exists()
    quarantine_files = list((store.root / "deadlettered_tasks").glob("*.json"))
    assert len(quarantine_files) == 1
    assert json.loads(quarantine_files[0].read_text(encoding="utf-8"))["status"] == "pending"
    assert list((store.root / "leases").glob("*")) == []
    assert list((store.root / "sessions").glob("*")) == []
    assert store.deadletter_file.exists()


def test_cmd_status_skips_invalid_task_filename_and_reports_valid_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store = StateStore(tmp_path / "state")
    store.write_task({"id": "task1", "status": "pending"})
    poison_file = store.root / "tasks" / "bad..id.json"
    poison_file.write_text(json.dumps({"status": "pending"}), encoding="utf-8")
    monkeypatch.setattr(boss_ctl, "StateStore", lambda: store)

    rc = boss_ctl.cmd_status(argparse.Namespace())

    captured = capsys.readouterr()
    assert rc == 0
    assert "task1: pending" in captured.out
    assert "skipping invalid task file" in captured.err


@pytest.mark.parametrize(
    "bad_task_id",
    ["../escape", "a/b", "", "bad\x1fcontrol"],
)
def test_cmd_write_validation_rejects_invalid_task_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad_task_id: str
) -> None:
    monkeypatch.chdir(tmp_path)
    args = argparse.Namespace(task_id=bad_task_id, outcome="pass", notes="n")

    with pytest.raises(ValueError):
        boss_ctl.cmd_write_validation(args)


def test_main_reports_invalid_task_id_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "boss_ctl.py",
            "write-validation",
            "--task-id",
            "../escape",
            "--outcome",
            "pass",
        ],
    )

    assert boss_ctl.main() == 2
    captured = capsys.readouterr()

    assert "ValueError" in captured.err
    assert "task_id must not contain '..'" in captured.err
    assert "Traceback" not in captured.err
