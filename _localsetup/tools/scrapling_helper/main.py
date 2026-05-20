"""
Purpose: Public entrypoints for Scrapling helper – env detection, install/upgrade core, and status reporting.
Created: 2026-03-16
Last Updated: 2026-03-16
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from .config import ScraplingConfig, load_config
from .host_env import (
    HostEnvStatus,
    apply_command_plan,
    detect_host_env,
    propose_pipx_bootstrap,
    propose_pipx_install,
)
from ..cli_helpers import augment_path_for_pipx_apps
from .docker_env import DockerEnvStatus, build_scrapling_docker_command, detect_docker
from .adapter_state import AdapterState, load_state, save_state, save_capability_index
from .adapter_parser import parse_current_features
from .job_registry import (
    JobRecord,
    JobRegistryError,
    cancel_job,
    create_job,
    load_job,
    list_jobs_with_errors,
    update_job,
    _utc_now_iso,
)


@dataclass
class ScraplingStatus:
    env_type: str
    scrapling_available: bool
    version: Optional[str]
    healthy: bool
    docker_available: bool
    details: str


@dataclass
class EnsureResult:
    status: ScraplingStatus
    plan: Optional[list[str]]
    applied: bool
    command_result: Optional[Dict[str, Any]]
    pipx_bootstrap_plans: Optional[list[list[str]]] = None


def scrapling_status() -> ScraplingStatus:
    cfg = load_config()
    host_status: HostEnvStatus = detect_host_env(cfg)
    docker_status: DockerEnvStatus = detect_docker()
    # Treat any non-missing host env with a responding CLI as healthy.
    version_marker = get_scrapling_version()
    healthy = bool(version_marker)
    details_parts = [host_status.details, docker_status.details]
    return ScraplingStatus(
        env_type=host_status.env_type,
        scrapling_available=host_status.scrapling_available,
        version=version_marker,
        healthy=healthy,
        docker_available=docker_status.available,
        details="; ".join(details_parts),
    )


def ensure_available(host_first: bool = True, dry_run: bool = False, auto_confirm: bool = False) -> EnsureResult:
    cfg = load_config()
    status_before = scrapling_status()
    if status_before.scrapling_available and status_before.healthy:
        return EnsureResult(
            status=status_before,
            plan=None,
            applied=False,
            command_result=None,
            pipx_bootstrap_plans=None,
        )

    plan: Optional[list[str]] = None
    command_result: Optional[Dict[str, Any]] = None

    # Detect whether pipx itself is available so we can surface bootstrap plans.
    pipx_present = bool(shutil.which(cfg.pipx_binary))
    pipx_bootstrap_plans: Optional[list[list[str]]] = None
    if not pipx_present:
        pipx_bootstrap_plans = propose_pipx_bootstrap(userland=True)

    if host_first:
        plan = propose_pipx_install(cfg)
    # Docker escape hatch planning can be added later if needed.

    if dry_run or plan is None:
        return EnsureResult(
            status=status_before,
            plan=plan,
            applied=False,
            command_result=None,
            pipx_bootstrap_plans=pipx_bootstrap_plans,
        )

    if not auto_confirm:
        # Return the plan without executing so a caller (for example, a tmux-based
        # workflow) can present it to the user and run it in an appropriate shell.
        return EnsureResult(
            status=status_before,
            plan=plan,
            applied=False,
            command_result=None,
            pipx_bootstrap_plans=pipx_bootstrap_plans,
        )

    command_result = apply_command_plan(plan)
    status_after = scrapling_status()
    return EnsureResult(
        status=status_after,
        plan=plan,
        applied=True,
        command_result=command_result,
        pipx_bootstrap_plans=pipx_bootstrap_plans,
    )


def get_scrapling_version() -> Optional[str]:
    """
    Best-effort version/health check for Scrapling.

    Scrapling does not support a --version flag, so we rely on a lightweight
    CLI startup check. When the host CLI is missing or unhealthy, we attempt
    a Docker-based check when available.
    """
    cfg = load_config()
    host_status: HostEnvStatus = detect_host_env(cfg)
    if host_status.scrapling_available:
        # Use a simple --help invocation as a proxy for CLI health.
        cmd = _build_scrapling_command(cfg, ["--help"], use_docker=False)
        result = apply_command_plan(cmd)
        if result.get("returncode", 1) == 0:
            # We do not have a structured version string, but we can signal that
            # the CLI is present and responding.
            return "available"

    docker_status: DockerEnvStatus = detect_docker()
    if not docker_status.available:
        return None
    # Call scrapling --help in Docker as a basic health probe.
    docker_probe_dir = cfg.cache_dir / "docker-health"
    docker_probe_dir.mkdir(parents=True, exist_ok=True)
    cmd = _build_scrapling_command(cfg, ["--help"], use_docker=True, workdir=docker_probe_dir)
    result = apply_command_plan(cmd)
    if result["returncode"] != 0:
        return None
    return "available"


def upgrade_scrapling(host: bool = True, dry_run: bool = False, auto_confirm: bool = False) -> Dict[str, Any]:
    """
    Guided upgrade workflow for Scrapling, matching the plan's constraints.
    """
    cfg = load_config()
    plans: list[list[str]] = []
    if host:
        from .host_env import propose_pipx_upgrade

        plans.append(propose_pipx_upgrade(cfg))
    else:
        plans.append(
            ["docker", "pull", cfg.docker_image],
        )

    if dry_run or not auto_confirm:
        return {
            "applied": False,
            "plans": [" ".join(p) for p in plans],
            "version_before": get_scrapling_version(),
            "version_after": None,
        }

    results = [apply_command_plan(p) for p in plans]
    return {
        "applied": True,
        "plans": [" ".join(p) for p in plans],
        "results": results,
        "version_before": None,
        "version_after": get_scrapling_version(),
    }


def show_status() -> str:
    status = scrapling_status()
    payload = {
        "env_type": status.env_type,
        "scrapling_available": status.scrapling_available,
        "version": status.version,
        "docker_available": status.docker_available,
        "details": status.details,
    }
    return json.dumps(payload, indent=2)


def _write_status_json(status_path: Path, payload: Dict[str, Any]) -> None:
    payload["status_path"] = str(status_path)
    payload["status_write"] = {
        "ok": True,
        "path": str(status_path),
    }
    try:
        text = json.dumps(payload, indent=2)
        status_path.write_text(text, encoding="utf-8")
    except (OSError, TypeError, ValueError) as exc:
        error = {
            "ok": False,
            "path": str(status_path),
            "error": str(exc),
            "error_type": type(exc).__name__,
        }
        payload["status_write"] = error
        payload["status_write_error"] = error


def _build_scrapling_command(
    cfg: ScraplingConfig,
    args: Sequence[str],
    use_docker: bool,
    workdir: Optional[Path] = None,
) -> list[str]:
    # Ensure pipx-managed apps are visible to this process before resolving the
    # Scrapling binary. This keeps PATH handling consistent for all helpers.
    augment_path_for_pipx_apps()
    if use_docker:
        return build_scrapling_docker_command(cfg, list(args), workdir=workdir)
    return ["scrapling", *args]


def extract_url_simple(
    url: str,
    output_path: Path,
    selector: Optional[str] = None,
    mode_hint: Optional[str] = None,
    use_docker: bool = False,
) -> Dict[str, Any]:
    """
    Run a single-URL extraction with an opinionated adaptive mode strategy.

    Behavior:
    - When mode_hint is provided, use it directly for a single attempt. Valid
      modes align with the Scrapling CLI cheat sheet: "get", "post", "put",
      "delete", "fetch", and "stealthy-fetch".
    - When mode_hint is None, start with "get" and, on failure, escalate once
      to a more expensive dynamic mode such as "fetch".
    The response includes an attempts list so callers can inspect each try.
    """
    cfg = load_config()
    attempts: list[Dict[str, Any]] = []

    # Ensure the output directory exists so CLI writes do not fail silently
    output_path.parent.mkdir(parents=True, exist_ok=True)

    def _run_once(mode: str) -> Dict[str, Any]:
        args: list[str] = ["extract", mode, url, str(output_path)]
        if selector:
            args.extend(["--css-selector", selector])
        cmd = _build_scrapling_command(cfg, args, use_docker=use_docker, workdir=output_path.parent)
        result = apply_command_plan(cmd)
        attempts.append(
            {
                "mode": mode,
                "returncode": result.get("returncode"),
                "stderr": result.get("stderr"),
            }
        )
        return result

    if mode_hint:
        final_mode = mode_hint
        result = _run_once(final_mode)
    else:
        # First attempt: cheap "get" mode.
        final_mode = "get"
        result = _run_once(final_mode)
        # Escalate once on non-zero return code to a dynamic browser-based mode.
        if result.get("returncode", 1) != 0:
            final_mode = "fetch"
            result = _run_once(final_mode)

    payload: Dict[str, Any] = {
        "command": result["command"],
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "mode": final_mode,
        "output_path": str(output_path),
        "attempts": attempts,
    }

    # Persist a status JSON alongside the output so agents limited to filesystem
    # inspection (for example, tmux-only flows) can reliably detect success,
    # failure, and failure reasons without needing live stdout/stderr.
    status_path = output_path.with_suffix(output_path.suffix + ".status.json")
    _write_status_json(status_path, payload)

    return payload


def extract_url_structured(
    url: str,
    output_path: Path,
    selectors_schema: Dict[str, str],
    mode_hint: Optional[str] = None,
    use_docker: bool = False,
) -> Dict[str, Any]:
    """
    Run a structured extraction with the same adaptive mode strategy used for
    simple extractions, but with a conservative escalation rule.
    """
    cfg = load_config()
    attempts: list[Dict[str, Any]] = []

    # Ensure the output directory exists so CLI writes do not fail silently
    output_path.parent.mkdir(parents=True, exist_ok=True)

    def _run_once(mode: str) -> Dict[str, Any]:
        # For v1 we pass a single root CSS selector and let Scrapling handle per-field logic on the client side.
        args: list[str] = ["extract", mode, url, str(output_path)]
        # Callers are expected to persist selectors_schema alongside the JSONL file.
        cmd = _build_scrapling_command(cfg, args, use_docker=use_docker, workdir=output_path.parent)
        result = apply_command_plan(cmd)
        attempts.append(
            {
                "mode": mode,
                "returncode": result.get("returncode"),
                "stderr": result.get("stderr"),
            }
        )
        return result

    if mode_hint:
        final_mode = mode_hint
        result = _run_once(final_mode)
    else:
        final_mode = "get"
        result = _run_once(final_mode)
        # For structured extractions, only escalate when the first attempt clearly fails.
        if result.get("returncode", 1) != 0:
            final_mode = "fetch"
            result = _run_once(final_mode)

    payload: Dict[str, Any] = {
        "command": result["command"],
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "mode": final_mode,
        "output_path": str(output_path),
        "selectors_schema": selectors_schema,
        "attempts": attempts,
    }

    status_path = output_path.with_suffix(output_path.suffix + ".status.json")
    _write_status_json(status_path, payload)

    return payload


def run_shell(use_docker: bool = False) -> Dict[str, Any]:
    cfg = load_config()
    args: list[str] = ["shell"]
    cmd = _build_scrapling_command(cfg, args, use_docker=use_docker)
    result = apply_command_plan(cmd)
    return result


def run_spider(
    project_dir: Path,
    spider_name: str,
    crawl_dir: Optional[Path] = None,
    extra_args: Optional[Sequence[str]] = None,
    use_docker: bool = False,
) -> Dict[str, Any]:
    cfg = load_config()
    args: list[str] = ["spider", spider_name]
    if crawl_dir:
        args.extend(["--crawldir", str(crawl_dir)])
    if extra_args:
        args.extend(list(extra_args))
    cmd = _build_scrapling_command(cfg, args, use_docker=use_docker, workdir=project_dir)
    # Record a job for this spider run; for now we treat it as a foreground job
    # and only persist basic metadata. Background execution can build on this.
    job = JobRecord(
        job_id=_utc_now_iso(),
        kind="spider",
        status="running",
        created_at=_utc_now_iso(),
        updated_at=_utc_now_iso(),
        command=cmd,
        workdir=str(project_dir),
    )
    create_job(cfg, job)
    result = apply_command_plan(cmd)
    # Update job with final status and optional error message.
    final_status = "succeeded" if result.get("returncode", 1) == 0 else "failed"
    job.error = result.get("stderr") or None
    update_job(cfg, job, status=final_status)
    result["job_id"] = job.job_id
    return result


def resume_spider(
    project_dir: Path,
    crawl_dir: Path,
    use_docker: bool = False,
) -> Dict[str, Any]:
    return run_spider(project_dir=project_dir, spider_name="", crawl_dir=crawl_dir, extra_args=None, use_docker=use_docker)


def scrapling_job_status(job_id: str) -> Dict[str, Any]:
    """
    Check the status of a previously recorded job.
    """
    cfg = load_config()
    try:
        job = load_job(cfg, job_id)
    except JobRegistryError as exc:
        return {"job_id": job_id, "found": False, **exc.as_dict()}
    if job is None:
        return {"job_id": job_id, "found": False, "reason": "job_not_found"}
    return {
        "job_id": job.job_id,
        "kind": job.kind,
        "status": job.status,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "command": job.command,
        "workdir": job.workdir,
        "pid": job.pid,
        "output_path": job.output_path,
        "error": job.error,
        "metadata": job.metadata,
    }


def scrapling_cancel_job(job_id: str) -> Dict[str, Any]:
    """
    Attempt to cancel a running job by job_id using the job registry.
    """
    cfg = load_config()
    return cancel_job(cfg, job_id)


def scrapling_list_jobs(kind: Optional[str] = None) -> Dict[str, Any]:
    """
    List known jobs, optionally filtered by kind.
    """
    cfg = load_config()
    jobs, errors = list_jobs_with_errors(cfg, kind=kind)
    return {
        "jobs": [
            {
                "job_id": j.job_id,
                "kind": j.kind,
                "status": j.status,
                "created_at": j.created_at,
                "updated_at": j.updated_at,
            }
            for j in jobs
        ],
        "errors": errors,
    }


def launch_mcp_server(
    mode: str = "host",
    use_docker: bool = False,
) -> Dict[str, Any]:
    """
    Launch Scrapling's MCP server using either host or Docker mode.
    The concrete entrypoint and flags can be refined once upstream docs are wired in.
    """
    cfg = load_config()
    args: list[str] = ["mcp-server"]
    if mode == "docker" or use_docker:
        cmd = _build_scrapling_command(cfg, args, use_docker=True)
    else:
        cmd = _build_scrapling_command(cfg, args, use_docker=False)
    return apply_command_plan(cmd)


def build_capability_index(cfg: ScraplingConfig) -> Dict[str, Any]:
    """Return the machine-readable helper capability index without writing files."""
    return {
        "scrapling_status": {
            "cli": "scrapling --help",
            "helper": "scrapling_status()",
            "description": "Detect Scrapling availability, environment type, Docker availability, and basic health.",
        },
        "extract_url_simple": {
            "cli": "scrapling extract <mode> <url> <output_path>",
            "helper": "extract_url_simple(url, output_path, selector=None, mode_hint=None, use_docker=False)",
            "description": "Single URL extraction to HTML/Markdown/text using modes like get, fetch, or stealthy-fetch.",
        },
        "extract_url_structured": {
            "cli": "scrapling extract <mode> <url> <output_path>",
            "helper": "extract_url_structured(url, output_path, selectors_schema, mode_hint=None, use_docker=False)",
            "description": "Single URL structured extraction to JSONL based on a selector schema.",
        },
        "run_spider": {
            "cli": "scrapling spider <name> [options]",
            "helper": "run_spider(project_dir, spider_name, crawl_dir=None, extra_args=None, use_docker=False)",
            "description": "Run a named Scrapling spider in a project directory.",
        },
        "scrapling_job_status": {
            "cli": "n/a (filesystem-backed job registry)",
            "helper": "scrapling_job_status(job_id)",
            "description": "Inspect the status of recorded Scrapling jobs.",
        },
        "scrapling_cancel_job": {
            "cli": "n/a (filesystem-backed job registry)",
            "helper": "scrapling_cancel_job(job_id)",
            "description": "Attempt to cancel a running Scrapling job by job_id.",
        },
        "upgrade_scrapling": {
            "cli": f"{cfg.pipx_binary} upgrade scrapling",
            "helper": "upgrade_scrapling(host=True, dry_run=False, auto_confirm=False)",
            "description": "Upgrade the Scrapling CLI via pipx or Docker.",
        },
        "refresh_adapters": {
            "cli": "scrapling --help; scrapling extract --help; scrapling spider --help",
            "helper": "refresh_adapters(dry_run=True)",
            "description": "Parse current CLI help output and refresh the adapter state model.",
        },
        "scrapling_self_test": {
            "cli": "scrapling extract get <fixture> <output_path>",
            "helper": "scrapling_self_test(mode='auto')",
            "description": "Run an offline-first self-test and write a status file.",
        },
    }


def refresh_adapters(dry_run: bool = True) -> Dict[str, Any]:
    """
    Parse current Scrapling CLI features and generate a structured diff
    against the persisted AdapterState. When dry_run is True, only the diff
    is returned. When dry_run is False, the new state is written as well.
    """
    cfg = load_config()
    state_before: AdapterState = load_state(cfg)
    observed_state: AdapterState = parse_current_features(cfg)

    diff = {
        "supported_versions_before": state_before.supported_versions,
        "supported_versions_after": observed_state.supported_versions,
        "cli_commands_before": list(state_before.cli_commands.keys()),
        "cli_commands_after": list(observed_state.cli_commands.keys()),
        "flags_added": sorted(set(observed_state.flags.keys()) - set(state_before.flags.keys())),
        "flags_removed": sorted(set(state_before.flags.keys()) - set(observed_state.flags.keys())),
    }
    capability_index = build_capability_index(cfg)

    if dry_run:
        return {"applied": False, "diff": diff, "capabilities": capability_index}
    save_state(cfg, observed_state)
    save_capability_index(cfg, capability_index)
    return {"applied": True, "diff": diff, "capabilities": capability_index}


def scrapling_self_test(mode: str = "auto") -> Dict[str, Any]:
    """
    Run a lightweight self-test of the Scrapling CLI integration.

    mode:
      - "auto": prefer an offline-style check using a local fixture.
      - "offline": force a local fixture-based extraction.
      - "online": allow a simple network call to a safe URL.
    """
    cfg = load_config()
    status = scrapling_status()
    ensure_result = ensure_available(dry_run=True, auto_confirm=False)

    chosen_mode = mode
    if mode == "auto":
        chosen_mode = "offline"

    test_result: Dict[str, Any] = {}
    output_path = cfg.outputs_root / "self_test_output.md"

    if chosen_mode == "offline":
        fixture_path = cfg.outputs_root / "self_test_fixture.html"
        if not fixture_path.exists():
            fixture_path.write_text("<html><body><h1>scrapling self test</h1></body></html>", encoding="utf-8")
        test_url = f"file://{fixture_path}"
        test_result = extract_url_simple(
            url=test_url,
            output_path=output_path,
            selector=None,
            mode_hint="get",
            use_docker=False,
        )
    elif chosen_mode == "online":
        test_url = "https://example.com/"
        test_result = extract_url_simple(
            url=test_url,
            output_path=output_path,
            selector=None,
            mode_hint="get",
            use_docker=False,
        )
    else:
        test_result = {
            "error": f"unsupported self-test mode: {mode}",
            "returncode": 1,
        }

    summary = {
        "env_status": asdict(status),
        "ensure_plan": ensure_result.plan,
        "pipx_bootstrap_plans": ensure_result.pipx_bootstrap_plans,
        "self_test_mode": chosen_mode,
        "self_test_result": test_result,
    }
    status_path = output_path.with_suffix(output_path.suffix + ".status.json")
    _write_status_json(status_path, summary)
    return summary
