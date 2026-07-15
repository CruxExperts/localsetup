"""
Purpose: Tests for Scrapling job registry and job lifecycle helpers.
Created: 2026-03-16
Last Updated: 2026-03-16
"""

from __future__ import annotations

from pathlib import Path

from ls.tools.scrapling_helper import config as scrapling_config
from ls.tools.scrapling_helper import job_registry


def test_create_and_load_job(tmp_path: Path, monkeypatch) -> None:
    # Force cache_dir to a temp location so tests do not touch real cache.
    cfg = scrapling_config.load_config()
    monkeypatch.setattr(cfg, "cache_dir", tmp_path / ".cache")

    job = job_registry.JobRecord(
        job_id="job-1",
        kind="spider",
        status="pending",
        created_at=job_registry._utc_now_iso(),
        updated_at=job_registry._utc_now_iso(),
        command=["echo", "hello"],
        workdir=str(tmp_path),
    )
    job_registry.create_job(cfg, job)

    loaded = job_registry.load_job(cfg, "job-1")
    assert loaded is not None
    assert loaded.job_id == "job-1"
    assert loaded.kind == "spider"


def test_list_jobs_filters_by_kind(tmp_path: Path, monkeypatch) -> None:
    cfg = scrapling_config.load_config()
    monkeypatch.setattr(cfg, "cache_dir", tmp_path / ".cache")

    # Two jobs with different kinds.
    for job_id, kind in (("job-a", "spider"), ("job-b", "dynamic_extract")):
        job = job_registry.JobRecord(
            job_id=job_id,
            kind=kind,
            status="pending",
            created_at=job_registry._utc_now_iso(),
            updated_at=job_registry._utc_now_iso(),
            command=["echo", job_id],
            workdir=str(tmp_path),
        )
        job_registry.create_job(cfg, job)

    all_jobs = job_registry.list_jobs(cfg)
    assert len(all_jobs) == 2

    spider_jobs = job_registry.list_jobs(cfg, kind="spider")
    assert len(spider_jobs) == 1
    assert spider_jobs[0].kind == "spider"
