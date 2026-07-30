from __future__ import annotations

import os
from typing import Any


MIN_TEST_WORKERS = 1
TEST_WORKERS_ENV = "LOCALSETUP_TEST_WORKERS"

def available_cpu_count() -> int | None:
    process_count = getattr(os, "process_cpu_count", None)
    if callable(process_count):
        available = process_count()
        if available:
            return available
    affinity = getattr(os, "sched_getaffinity", None)
    if callable(affinity):
        try:
            available = len(affinity(0))
        except OSError:
            available = 0
        if available:
            return available
    return os.cpu_count()

def effective_max_test_workers(cpu_count: int | None = None) -> int:
    available = cpu_count if cpu_count is not None else available_cpu_count()
    if available is None:
        return MIN_TEST_WORKERS
    return max(MIN_TEST_WORKERS, available // 3)


def clamp_test_workers(value: int, *, cpu_count: int | None = None) -> int:
    return min(effective_max_test_workers(cpu_count), max(MIN_TEST_WORKERS, value))


def default_test_workers(cpu_count: int | None = None) -> int:
    return effective_max_test_workers(cpu_count)


def parse_test_worker_override(
    value: str, *, field: str = "test workers", cpu_count: int | None = None
) -> int:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field} must be an integer")
    try:
        parsed = int(stripped, 10)
    except ValueError as exc:
        raise ValueError(f"{field} must be an integer") from exc
    return clamp_test_workers(parsed, cpu_count=cpu_count)


def resolved_test_workers(override: str | int | None = None, *, cpu_count: int | None = None, env: dict[str, str] | None = None) -> int:
    if override is not None:
        if isinstance(override, int):
            return clamp_test_workers(override, cpu_count=cpu_count)
        return parse_test_worker_override(str(override), field="--workers", cpu_count=cpu_count)
    environ = env if env is not None else os.environ
    env_value = environ.get(TEST_WORKERS_ENV)
    if env_value is not None:
        return parse_test_worker_override(env_value, field=TEST_WORKERS_ENV, cpu_count=cpu_count)
    return default_test_workers(cpu_count)


def test_workers_payload(
    override: str | int | None = None,
    *,
    cpu_count: int | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    available = cpu_count if cpu_count is not None else available_cpu_count()
    workers = resolved_test_workers(override, cpu_count=cpu_count, env=env)
    return {
        "ok": True,
        "workers": workers,
        "available_cpu_cores": available,
        "default_formula": "floor(available_cpu_cores / 3), minimum 1",
        "min_workers": MIN_TEST_WORKERS,
        "max_workers": effective_max_test_workers(cpu_count),
        "override_env": TEST_WORKERS_ENV,
    }
