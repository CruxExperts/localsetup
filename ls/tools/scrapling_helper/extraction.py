"""Scrapling extraction command helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence

from .config import ScraplingConfig

CommandRunner = Callable[[list[str]], Dict[str, Any]]
CommandBuilder = Callable[[ScraplingConfig, Sequence[str], bool, Optional[Path]], list[str]]
StatusWriter = Callable[[Path, Dict[str, Any]], None]


def extract_url_simple(
    cfg: ScraplingConfig,
    apply_command_plan: CommandRunner,
    build_scrapling_command: CommandBuilder,
    write_status_json: StatusWriter,
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
    attempts: list[Dict[str, Any]] = []

    # Ensure the output directory exists so CLI writes do not fail silently
    output_path.parent.mkdir(parents=True, exist_ok=True)

    def _run_once(mode: str) -> Dict[str, Any]:
        args: list[str] = ["extract", mode, url, str(output_path)]
        if selector:
            args.extend(["--css-selector", selector])
        cmd = build_scrapling_command(cfg, args, use_docker, output_path.parent)
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
    write_status_json(status_path, payload)

    return payload


def extract_url_structured(
    cfg: ScraplingConfig,
    apply_command_plan: CommandRunner,
    build_scrapling_command: CommandBuilder,
    write_status_json: StatusWriter,
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
    attempts: list[Dict[str, Any]] = []

    # Ensure the output directory exists so CLI writes do not fail silently
    output_path.parent.mkdir(parents=True, exist_ok=True)

    def _run_once(mode: str) -> Dict[str, Any]:
        args: list[str] = ["extract", mode, url, str(output_path)]
        cmd = build_scrapling_command(cfg, args, use_docker, output_path.parent)
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
    write_status_json(status_path, payload)

    return payload
