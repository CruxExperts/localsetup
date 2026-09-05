"""Scrapling extraction command helpers."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, Optional, Sequence

from .config import ScraplingConfig


CommandRunner = Callable[[list[str]], Dict[str, Any]]
CommandBuilder = Callable[[ScraplingConfig, Sequence[str], bool, Optional[Path]], list[str]]
StatusWriter = Callable[[Path, Dict[str, Any]], None]
SUPPORTED_EXTRACTION_MODES = (
    "get",
    "post",
    "put",
    "delete",
    "fetch",
    "stealthy-fetch",
)


def _validate_mode_hint(mode_hint: Optional[str]) -> Optional[str]:
    if mode_hint is None:
        return None
    if mode_hint not in SUPPORTED_EXTRACTION_MODES:
        expected = ", ".join(SUPPORTED_EXTRACTION_MODES)
        raise ValueError(
            f"unsupported Scrapling extraction mode {mode_hint!r}; expected one of: {expected}",
        )
    return mode_hint


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
    """Run one supported Scrapling extraction with conservative adaptation."""
    validated_mode_hint = _validate_mode_hint(mode_hint)
    attempts: list[Dict[str, Any]] = []

    output_path.parent.mkdir(parents=True, exist_ok=True)
    command_output_path = (
        str(PurePosixPath("/workspace") / output_path.name)
        if use_docker
        else str(output_path)
    )

    def _run_once(mode: str) -> Dict[str, Any]:
        args: list[str] = ["extract", mode, url, command_output_path]
        if selector:
            args.extend(["--css-selector", selector])
        cmd = build_scrapling_command(cfg, args, use_docker, output_path.parent)
        result = apply_command_plan(cmd)
        attempts.append(
            {
                "mode": mode,
                "returncode": result.get("returncode"),
                "stderr": result.get("stderr"),
            },
        )
        return result

    if validated_mode_hint:
        final_mode = validated_mode_hint
        result = _run_once(final_mode)
    else:
        final_mode = "get"
        result = _run_once(final_mode)
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

    status_path = output_path.with_suffix(output_path.suffix + ".status.json")
    write_status_json(status_path, payload)

    return payload
