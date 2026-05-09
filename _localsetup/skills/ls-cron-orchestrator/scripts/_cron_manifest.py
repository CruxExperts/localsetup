#!/usr/bin/env python3
"""Shared manifest loading and validation for the cron orchestrator."""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - exercised only without PyYAML
    yaml = None
    YAML_IMPORT_ERROR: ImportError | None = exc
else:
    YAML_IMPORT_ERROR = None


MAX_CMD_LEN = 8192
MAX_ID_LEN = 128
MAX_TRIGGER_LEN = 128
MAX_TIMEOUT_SECONDS = 86400
MAX_DELAY_SECONDS = 86400
MAX_BOOT_DELAY_MINUTES = 1440
DEFAULT_TIMEOUT_SECONDS = 3600

IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_.:@+-]+$")
CRON_FIELD_RE = re.compile(r"^[A-Za-z0-9*/,\-?#LW]+$")
SHELL_OPERATOR_TOKENS = ("&&", "||", ";", "|", ">", "<", "`", "\n", "\r", "$(", "${")


class ManifestError(ValueError):
    """Raised when a cron manifest is missing, malformed, or unsafe."""


def _require_yaml() -> Any:
    if yaml is None:
        detail = f" ({YAML_IMPORT_ERROR})" if YAML_IMPORT_ERROR else ""
        raise ManifestError(
            "PyYAML is required to read cron manifests. "
            "Install repository dependencies with: "
            "python3 -m pip install -r _localsetup/requirements.txt"
            f"{detail}"
        )
    return yaml


def load_manifest(path: Path) -> dict[str, Any]:
    """Load a YAML manifest and ensure the root object is a mapping."""

    yaml_module = _require_yaml()
    if not path.is_file():
        raise ManifestError(f"Not a file: {path}")
    try:
        raw = path.read_text(encoding="utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ManifestError(f"Manifest is not valid UTF-8: {exc}") from exc
    except OSError as exc:
        raise ManifestError(f"Failed to read manifest: {exc}") from exc
    try:
        data = yaml_module.safe_load(raw)
    except Exception as exc:
        raise ManifestError(f"Failed to parse YAML: {exc}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ManifestError("Manifest root must be a mapping with 'triggers' and optional 'tasks'")
    return data


def dump_manifest(path: Path, data: dict[str, Any]) -> None:
    yaml_module = _require_yaml()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("w", encoding="utf-8") as handle:
            yaml_module.safe_dump(data, handle, default_flow_style=False, sort_keys=False, allow_unicode=True)
    except OSError as exc:
        raise ManifestError(f"Failed to write manifest: {exc}") from exc


def clean_display(value: Any, max_len: int) -> str:
    text = str(value)
    out = "".join(ch for ch in text if ord(ch) >= 0x20 and ord(ch) != 0x7F)
    out = " ".join(out.split()).strip()
    return out[:max_len]


def validate_identifier(value: Any, path: str, max_len: int) -> str:
    if not isinstance(value, str):
        raise ManifestError(f"{path}: must be a string")
    if not value:
        raise ManifestError(f"{path}: must not be empty")
    if len(value) > max_len:
        raise ManifestError(f"{path}: must be at most {max_len} characters")
    if not IDENTIFIER_RE.fullmatch(value):
        raise ManifestError(f"{path}: use only letters, numbers, '.', '_', ':', '@', '+', or '-'")
    return value


def _reject_control_chars(value: str, path: str) -> None:
    for char in value:
        if ord(char) < 0x20 or ord(char) == 0x7F:
            raise ManifestError(f"{path}: control characters are not allowed")


def contains_shell_operators(command: str) -> bool:
    return any(token in command for token in SHELL_OPERATOR_TOKENS)


def normalize_command(raw: Any, path: str) -> list[str]:
    if isinstance(raw, list):
        argv: list[str] = []
        for index, part in enumerate(raw):
            part_path = f"{path}[{index}]"
            if not isinstance(part, str):
                raise ManifestError(f"{part_path}: argv entries must be strings")
            if not part:
                raise ManifestError(f"{part_path}: argv entries must not be empty")
            if len(part) > MAX_CMD_LEN:
                raise ManifestError(f"{part_path}: argv entry exceeds {MAX_CMD_LEN} characters")
            _reject_control_chars(part, part_path)
            argv.append(part)
        if not argv:
            raise ManifestError(f"{path}: command list must not be empty")
        if sum(len(part) for part in argv) > MAX_CMD_LEN:
            raise ManifestError(f"{path}: combined argv length exceeds {MAX_CMD_LEN} characters")
        return argv
    if not isinstance(raw, str):
        raise ManifestError(f"{path}: command must be a string or list of argv entries")
    command = raw.strip()
    if not command:
        raise ManifestError(f"{path}: command must not be empty")
    if len(command) > MAX_CMD_LEN:
        raise ManifestError(f"{path}: command exceeds {MAX_CMD_LEN} characters")
    _reject_control_chars(command, path)
    if contains_shell_operators(command):
        raise ManifestError(f"{path}: contains unsupported shell operators; use an argv list for literal arguments")
    try:
        argv = shlex.split(command, posix=True)
    except ValueError as exc:
        raise ManifestError(f"{path}: invalid command quoting: {exc}") from exc
    if not argv:
        raise ManifestError(f"{path}: command is empty after parsing")
    return argv


def normalize_timeout(value: Any, path: str) -> int:
    if value is None:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        timeout = int(value)
    except (TypeError, ValueError) as exc:
        raise ManifestError(f"{path}: must be an integer") from exc
    if timeout < 1 or timeout > MAX_TIMEOUT_SECONDS:
        raise ManifestError(f"{path}: must be in the range 1..{MAX_TIMEOUT_SECONDS}")
    return timeout


def normalize_delay_seconds(value: Any, path: str) -> int:
    try:
        delay = int(value)
    except (TypeError, ValueError) as exc:
        raise ManifestError(f"{path}: must be an integer") from exc
    if delay < 0 or delay > MAX_DELAY_SECONDS:
        raise ManifestError(f"{path}: must be in the range 0..{MAX_DELAY_SECONDS}")
    return delay


def normalize_boot_delay_minutes(value: Any, path: str) -> int:
    try:
        delay = int(value)
    except (TypeError, ValueError) as exc:
        raise ManifestError(f"{path}: must be an integer") from exc
    if delay < 0 or delay > MAX_BOOT_DELAY_MINUTES:
        raise ManifestError(f"{path}: must be in the range 0..{MAX_BOOT_DELAY_MINUTES}")
    return delay


def validate_schedule(value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise ManifestError(f"{path}: schedule must be a string")
    schedule = " ".join(value.split())
    if not schedule:
        raise ManifestError(f"{path}: schedule must not be empty")
    fields = schedule.split(" ")
    if len(fields) != 5:
        raise ManifestError(f"{path}: expected 5 cron fields, got {len(fields)}")
    for index, field in enumerate(fields, start=1):
        if len(field) > 64:
            raise ManifestError(f"{path}: field {index} exceeds 64 characters")
        if not CRON_FIELD_RE.fullmatch(field):
            raise ManifestError(f"{path}: field {index} contains unsupported cron characters")
    return schedule


def validate_manifest(data: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    normalized_triggers: dict[str, dict[str, Any]] = {}
    normalized_tasks: list[dict[str, Any]] = []

    triggers = data.get("triggers")
    if not isinstance(triggers, dict) or not triggers:
        errors.append("triggers: must be a non-empty mapping")
    else:
        for raw_name, raw_cfg in triggers.items():
            path = f"triggers.{raw_name}"
            try:
                name = validate_identifier(raw_name, path, MAX_TRIGGER_LEN)
                if not isinstance(raw_cfg, dict):
                    raise ManifestError(f"{path}: trigger config must be a mapping")
                has_schedule = "schedule" in raw_cfg
                has_boot_delay = "on_boot_delay_minutes" in raw_cfg
                if has_schedule == has_boot_delay:
                    raise ManifestError(f"{path}: specify exactly one of schedule or on_boot_delay_minutes")
                if has_schedule:
                    normalized_triggers[name] = {"schedule": validate_schedule(raw_cfg.get("schedule"), f"{path}.schedule")}
                else:
                    minutes = normalize_boot_delay_minutes(raw_cfg.get("on_boot_delay_minutes"), f"{path}.on_boot_delay_minutes")
                    normalized_triggers[name] = {"on_boot_delay_minutes": minutes}
            except ManifestError as exc:
                errors.append(str(exc))

    tasks = data.get("tasks", [])
    if tasks is None:
        tasks = []
    if not isinstance(tasks, list):
        errors.append("tasks: must be a list when present")
    else:
        seen_ids: set[str] = set()
        for index, raw_task in enumerate(tasks):
            path = f"tasks[{index}]"
            try:
                if not isinstance(raw_task, dict):
                    raise ManifestError(f"{path}: task must be a mapping")
                task_id = validate_identifier(raw_task.get("id"), f"{path}.id", MAX_ID_LEN)
                if task_id in seen_ids:
                    raise ManifestError(f"{path}.id: duplicate task id {task_id!r}")
                seen_ids.add(task_id)
                trigger = validate_identifier(raw_task.get("trigger"), f"{path}.trigger", MAX_TRIGGER_LEN)
                if normalized_triggers and trigger not in normalized_triggers:
                    raise ManifestError(f"{path}.trigger: unknown trigger {trigger!r}")
                try:
                    sequence_order = int(raw_task.get("sequence_order", 0))
                except (TypeError, ValueError) as exc:
                    raise ManifestError(f"{path}.sequence_order: must be an integer") from exc
                if sequence_order < 0:
                    raise ManifestError(f"{path}.sequence_order: must be greater than or equal to 0")
                enabled = raw_task.get("enabled", True)
                if not isinstance(enabled, bool):
                    raise ManifestError(f"{path}.enabled: must be a boolean")
                argv = normalize_command(raw_task.get("command"), f"{path}.command")
                timeout = normalize_timeout(raw_task.get("timeout_seconds"), f"{path}.timeout_seconds")
                normalized_tasks.append(
                    {
                        "id": task_id,
                        "trigger": trigger,
                        "sequence_order": sequence_order,
                        "enabled": enabled,
                        "argv": argv,
                        "timeout_seconds": timeout,
                        "command": raw_task.get("command"),
                    }
                )
            except ManifestError as exc:
                errors.append(str(exc))

    if errors:
        details = "\n- ".join(errors)
        raise ManifestError(f"Manifest validation failed:\n- {details}")
    return {"triggers": normalized_triggers, "tasks": normalized_tasks}
