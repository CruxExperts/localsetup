from __future__ import annotations

import math
import os
from typing import Any


MIN_TEST_WORKERS = 1
MAX_TEST_WORKERS = 255
TEST_WORKERS_ENV = "LOCALSETUP_TEST_WORKERS"


def clamp_test_workers(value: int) -> int:
    return min(MAX_TEST_WORKERS, max(MIN_TEST_WORKERS, value))


def default_test_workers(cpu_count: int | None = None) -> int:
    available = cpu_count if cpu_count is not None else os.cpu_count()
    if available is None:
        return MIN_TEST_WORKERS
    return clamp_test_workers(math.ceil(max(available, MIN_TEST_WORKERS) / 2))


def parse_test_worker_override(value: str, *, field: str = "test workers") -> int:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field} must be an integer")
    try:
        parsed = int(stripped, 10)
    except ValueError as exc:
        raise ValueError(f"{field} must be an integer") from exc
    return clamp_test_workers(parsed)


def resolved_test_workers(override: str | int | None = None, *, cpu_count: int | None = None, env: dict[str, str] | None = None) -> int:
    if override is not None:
        if isinstance(override, int):
            return clamp_test_workers(override)
        return parse_test_worker_override(str(override), field="--workers")
    environ = env if env is not None else os.environ
    env_value = environ.get(TEST_WORKERS_ENV)
    if env_value is not None:
        return parse_test_worker_override(env_value, field=TEST_WORKERS_ENV)
    return default_test_workers(cpu_count)


def test_workers_payload(override: str | int | None = None, *, cpu_count: int | None = None, env: dict[str, str] | None = None) -> dict[str, Any]:
    available = cpu_count if cpu_count is not None else os.cpu_count()
    workers = resolved_test_workers(override, cpu_count=cpu_count, env=env)
    return {
        "ok": True,
        "workers": workers,
        "available_cpu_cores": available,
        "default_formula": "ceil(available_cpu_cores / 2)",
        "min_workers": MIN_TEST_WORKERS,
        "max_workers": MAX_TEST_WORKERS,
        "override_env": TEST_WORKERS_ENV,
    }
