"""
Purpose: Focused tests for Scrapling helper registry and status-file contracts.
Created: 2026-05-09
Last Updated: 2026-05-09
"""

from __future__ import annotations

import json
from pathlib import Path

from _localsetup.tools.scrapling_helper import config as scrapling_config
from _localsetup.tools.scrapling_helper import job_registry
from _localsetup.tools.scrapling_helper import main as scrapling_main


def _temp_cfg(tmp_path: Path):
    cfg = scrapling_config.load_config()
    cfg.cache_dir = tmp_path / ".cache"
    cfg.logs_dir = tmp_path / "logs"
    cfg.outputs_root = tmp_path / "out"
    cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    cfg.logs_dir.mkdir(parents=True, exist_ok=True)
    cfg.outputs_root.mkdir(parents=True, exist_ok=True)
    return cfg


def test_cancel_job_uses_os_kill_and_marks_cancelling(tmp_path: Path, monkeypatch) -> None:
    cfg = _temp_cfg(tmp_path)
    sent: list[tuple[int, int]] = []

    def fake_kill(pid: int, sig: int) -> None:
        sent.append((pid, sig))

    monkeypatch.setattr(job_registry.os, "kill", fake_kill)
    job = job_registry.JobRecord(
        job_id="running-job",
        kind="spider",
        status="running",
        created_at=job_registry._utc_now_iso(),
        updated_at=job_registry._utc_now_iso(),
        command=["scrapling", "spider", "demo"],
        workdir=str(tmp_path),
        pid=12345,
    )
    job_registry.create_job(cfg, job)

    result = job_registry.cancel_job(cfg, "running-job")

    assert result == {"job_id": "running-job", "cancelled": True, "status": "cancelling"}
    assert sent == [(12345, job_registry.signal.SIGTERM)]
    loaded = job_registry.load_job(cfg, "running-job")
    assert loaded is not None
    assert loaded.status == "cancelling"


def test_scrapling_job_status_reports_malformed_registry_entry(tmp_path: Path, monkeypatch) -> None:
    cfg = _temp_cfg(tmp_path)
    monkeypatch.setattr(scrapling_main, "load_config", lambda: cfg)
    bad_path = job_registry._job_path(cfg, "bad-job")
    bad_path.write_text("{not-json", encoding="utf-8")

    result = scrapling_main.scrapling_job_status("bad-job")

    assert result["found"] is False
    assert result["reason"] == "registry_entry_malformed_json"
    assert result["path"] == str(bad_path)
    assert "line" in result["error"]


def test_scrapling_list_jobs_keeps_valid_jobs_and_reports_bad_entries(tmp_path: Path, monkeypatch) -> None:
    cfg = _temp_cfg(tmp_path)
    monkeypatch.setattr(scrapling_main, "load_config", lambda: cfg)
    valid = job_registry.JobRecord(
        job_id="good-job",
        kind="spider",
        status="succeeded",
        created_at=job_registry._utc_now_iso(),
        updated_at=job_registry._utc_now_iso(),
        command=["echo", "ok"],
        workdir=str(tmp_path),
    )
    job_registry.create_job(cfg, valid)
    job_registry._job_path(cfg, "bad-job").write_text("[]", encoding="utf-8")

    result = scrapling_main.scrapling_list_jobs()

    assert [job["job_id"] for job in result["jobs"]] == ["good-job"]
    assert len(result["errors"]) == 1
    assert result["errors"][0]["reason"] == "registry_entry_invalid"


def test_cancel_job_reports_invalid_pid_registry_entry(tmp_path: Path) -> None:
    cfg = _temp_cfg(tmp_path)
    bad_path = job_registry._job_path(cfg, "bad-pid")
    bad_path.write_text(
        json.dumps(
            {
                "job_id": "bad-pid",
                "kind": "spider",
                "status": "running",
                "created_at": job_registry._utc_now_iso(),
                "updated_at": job_registry._utc_now_iso(),
                "command": ["scrapling", "spider", "demo"],
                "workdir": str(tmp_path),
                "pid": "12345",
            }
        ),
        encoding="utf-8",
    )

    result = job_registry.cancel_job(cfg, "bad-pid")

    assert result["cancelled"] is False
    assert result["reason"] == "registry_entry_invalid"
    assert result["path"] == str(bad_path)


def test_status_write_error_keeps_context(tmp_path: Path, monkeypatch) -> None:
    def fake_apply(plan: list[str]) -> dict:
        return {"command": " ".join(plan), "returncode": 0, "stdout": "", "stderr": ""}

    def fake_json_dumps(_payload, indent=None):
        raise TypeError("not serializable")

    monkeypatch.setattr(scrapling_main, "apply_command_plan", fake_apply)
    monkeypatch.setattr(scrapling_main.json, "dumps", fake_json_dumps)

    result = scrapling_main.extract_url_simple("https://example.com", tmp_path / "out.md", mode_hint="get")

    assert result["status_write"]["ok"] is False
    assert result["status_write"]["error_type"] == "TypeError"
    assert result["status_write"]["path"] == result["status_path"]


def test_status_file_includes_status_write_context(tmp_path: Path, monkeypatch) -> None:
    def fake_apply(plan: list[str]) -> dict:
        return {"command": " ".join(plan), "returncode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(scrapling_main, "apply_command_plan", fake_apply)

    result = scrapling_main.extract_url_simple("https://example.com", tmp_path / "out.md", mode_hint="get")
    status_payload = json.loads(Path(result["status_path"]).read_text(encoding="utf-8"))

    assert result["status_write"]["ok"] is True
    assert status_payload["status_write"]["ok"] is True
    assert status_payload["status_path"] == result["status_path"]
