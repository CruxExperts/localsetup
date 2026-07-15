#!/usr/bin/env python3
"""Codex heartbeat harness runtime with atomic run artifacts."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

for parent in Path(__file__).resolve().parents:
    if (parent / "lib" / "deps.py").is_file():
        sys.path.insert(0, str(parent / "lib"))
        from deps import require_deps

        require_deps(["yaml"])
        break

try:
    import yaml
except ImportError as exc:  # pragma: no cover - environment guidance
    raise SystemExit("Missing dependency: PyYAML. Run `uv sync --locked --no-dev` from the Localsetup source checkout.") from exc

sys.path.insert(0, str(Path(__file__).resolve().parent))
from codex_heartbeat_support import ACTIVE_NAME
from codex_heartbeat_support import DEFAULT_COMMAND_TIMEOUT
from codex_heartbeat_support import LATEST_NAME
from codex_heartbeat_support import LOCK_NAME
from codex_heartbeat_support import MAX_COMMAND_TIMEOUT
from codex_heartbeat_support import MAX_TAIL_CHARS
from codex_heartbeat_support import RUNS_DIR_NAME
from codex_heartbeat_support import SCHEMA_VERSION
from codex_heartbeat_support import STATE_DIR_DEFAULT
from codex_heartbeat_support import HeartbeatError
from codex_heartbeat_support import atomic_write_json
from codex_heartbeat_support import atomic_write_text
from codex_heartbeat_support import command_policy
from codex_heartbeat_support import config_path_for
from codex_heartbeat_support import heartbeat_enabled
from codex_heartbeat_support import load_codex_command
from codex_heartbeat_support import load_hooks
from codex_heartbeat_support import load_yaml
from codex_heartbeat_support import normalize_timeout
from codex_heartbeat_support import plan_summary
from codex_heartbeat_support import planned_commands
from codex_heartbeat_support import run_command
from codex_heartbeat_support import sha256_file
from codex_heartbeat_support import sha256_json
from codex_heartbeat_support import state_root_from_config
from codex_heartbeat_support import utc_now
from codex_heartbeat_support import validate_direct_command

def _ensure_state_dirs(state_root: Path) -> Path:
    runs = state_root / RUNS_DIR_NAME
    runs.mkdir(parents=True, exist_ok=True)
    return runs


def _is_relative_child(value: str, base: Path) -> Path:
    if not value or Path(value).is_absolute() or ".." in Path(value).parts:
        raise HeartbeatError("pointer path must be a relative path inside state")
    resolved = (base / value).resolve()
    try:
        resolved.relative_to(base.resolve())
    except ValueError as exc:
        raise HeartbeatError("pointer path escapes heartbeat state") from exc
    return resolved


def validate_active_pointer(state_root: Path) -> dict[str, Any] | None:
    pointer = state_root / ACTIVE_NAME
    if not pointer.exists():
        return None
    try:
        data = json.loads(pointer.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HeartbeatError("active pointer is not valid JSON") from exc
    if not isinstance(data, dict):
        raise HeartbeatError("active pointer must be a JSON object")
    path_value = str(data.get("path") or "")
    active_path = _is_relative_child(path_value, state_root)
    if not active_path.exists():
        pointer.unlink()
        return None
    return data


def validate_latest_pointer(state_root: Path) -> dict[str, Any] | None:
    pointer = state_root / LATEST_NAME
    if not pointer.exists():
        return None
    try:
        data = json.loads(pointer.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HeartbeatError("latest pointer is not valid JSON") from exc
    if not isinstance(data, dict):
        raise HeartbeatError("latest pointer must be a JSON object")
    run_path = _is_relative_child(str(data.get("path") or ""), state_root)
    manifest = run_path / "manifest.json"
    if not manifest.is_file():
        raise HeartbeatError("latest pointer references a run without manifest.json")
    expected_hash = data.get("manifest_sha256")
    if expected_hash and expected_hash != sha256_file(manifest):
        raise HeartbeatError("latest pointer manifest hash mismatch")
    return data


def recover_staged_runs(state_root: Path) -> list[dict[str, Any]]:
    runs = _ensure_state_dirs(state_root)
    recovered: list[dict[str, Any]] = []
    for staged in sorted(runs.glob("*.staged")):
        if not staged.is_dir():
            continue
        manifest_path = staged / "manifest.json"
        manifest: dict[str, Any]
        if manifest_path.is_file():
            try:
                loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest = loaded if isinstance(loaded, dict) else {}
            except json.JSONDecodeError:
                manifest = {}
        else:
            manifest = {}
        manifest.update(
            {
                "schema_version": SCHEMA_VERSION,
                "status": "failed_recovered",
                "recovered_at": utc_now(),
                "recovery_reason": "staged run was present before a new run started",
            }
        )
        atomic_write_json(manifest_path, manifest)
        suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        recovered_path = staged.with_name(f"{staged.name.removesuffix('.staged')}.recovered-{suffix}")
        counter = 1
        while recovered_path.exists():
            counter += 1
            recovered_path = staged.with_name(f"{staged.name.removesuffix('.staged')}.recovered-{suffix}-{counter}")
        os.replace(staged, recovered_path)
        recovered.append({"from": staged.name, "to": recovered_path.name, "status": "failed_recovered"})
    active = state_root / ACTIVE_NAME
    if active.exists():
        try:
            validate_active_pointer(state_root)
        except HeartbeatError:
            raise
        if active.exists():
            active.unlink()
    return recovered


def acquire_lock(state_root: Path) -> tuple[bool, dict[str, Any]]:
    state_root.mkdir(parents=True, exist_ok=True)
    lock_path = state_root / LOCK_NAME
    payload = {
        "pid": os.getpid(),
        "created_at": utc_now(),
        "hostname": os.uname().nodename if hasattr(os, "uname") else "",
    }
    try:
        fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        try:
            existing = json.loads(lock_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {"path": str(lock_path)}
        return False, existing if isinstance(existing, dict) else {"path": str(lock_path)}
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return True, payload


def release_lock(state_root: Path) -> None:
    lock_path = state_root / LOCK_NAME
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


def validate_staged_run(staged: Path) -> dict[str, Any]:
    if not staged.is_dir():
        raise HeartbeatError(f"staged run is not a directory: {staged}")
    manifest_path = staged / "manifest.json"
    if not manifest_path.is_file():
        raise HeartbeatError("staged run missing manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HeartbeatError("staged manifest is not valid JSON") from exc
    if not isinstance(manifest, dict):
        raise HeartbeatError("staged manifest must be an object")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise HeartbeatError("staged manifest schema_version mismatch")
    if manifest.get("status") not in {"succeeded", "failed", "skipped"}:
        raise HeartbeatError("staged manifest status is not final")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise HeartbeatError("staged manifest must include artifact hashes")
    for name, expected in artifacts.items():
        path = staged / str(name)
        if not path.is_file():
            raise HeartbeatError(f"staged artifact missing: {name}")
        if sha256_file(path) != expected:
            raise HeartbeatError(f"staged artifact hash mismatch: {name}")
    return manifest


def promote_staged_run(staged: Path, state_root: Path) -> dict[str, Any]:
    manifest = validate_staged_run(staged)
    run_id = str(manifest.get("run_id") or staged.name.removesuffix(".staged"))
    final = state_root / RUNS_DIR_NAME / run_id
    if final.exists():
        raise HeartbeatError(f"run already exists: {run_id}")
    os.replace(staged, final)
    manifest_hash = sha256_file(final / "manifest.json")
    latest = {
        "run_id": run_id,
        "path": f"{RUNS_DIR_NAME}/{run_id}",
        "status": manifest.get("status"),
        "manifest_sha256": manifest_hash,
        "updated_at": utc_now(),
    }
    atomic_write_json(state_root / LATEST_NAME, latest)
    return latest


def _new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{os.getpid()}"


def _write_active_pointer(state_root: Path, staged: Path, run_id: str) -> None:
    rel = staged.relative_to(state_root).as_posix()
    atomic_write_json(state_root / ACTIVE_NAME, {"run_id": run_id, "path": rel, "created_at": utc_now()})


def _finalize_staged(
    staged: Path,
    *,
    manifest: dict[str, Any],
    result: dict[str, Any],
    command_log: dict[str, Any],
) -> dict[str, Any]:
    atomic_write_json(staged / "heartbeat-result.json", result)
    atomic_write_json(staged / "command-log.json", command_log)
    artifacts = {
        "heartbeat-result.json": sha256_file(staged / "heartbeat-result.json"),
        "command-log.json": sha256_file(staged / "command-log.json"),
    }
    manifest["artifacts"] = artifacts
    atomic_write_json(staged / "manifest.json", manifest)
    return manifest


def run_once(
    *,
    target_root: Path,
    config_path: Path | None = None,
    no_agent: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    target_root = target_root.resolve()
    config_path = config_path or config_path_for(target_root)
    config = load_yaml(config_path)
    state_root = state_root_from_config(target_root, config)
    if not heartbeat_enabled(config) and not force:
        return {
            "ok": True,
            "status": "skipped",
            "reason": "heartbeat.disabled",
            "target_root": str(target_root),
            "config_path": str(config_path),
        }
    recovered = recover_staged_runs(state_root)
    validate_active_pointer(state_root)
    locked, lock_payload = acquire_lock(state_root)
    if not locked:
        return {"ok": False, "status": "locked", "lock": lock_payload, "target_root": str(target_root)}
    run_id = _new_run_id()
    staged = state_root / RUNS_DIR_NAME / f"{run_id}.staged"
    command_entries: list[dict[str, Any]] = []
    try:
        staged.mkdir(parents=True, exist_ok=False)
        _write_active_pointer(state_root, staged, run_id)
        config_hash = sha256_json(config)
        manifest: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "status": "running",
            "started_at": utc_now(),
            "target_root": str(target_root),
            "config_path": str(config_path),
            "config_sha256": config_hash,
            "pid": os.getpid(),
            "sid": os.getsid(0) if hasattr(os, "getsid") else None,
            "pgid": os.getpgrp() if hasattr(os, "getpgrp") else None,
            "recovered_before_run": recovered,
        }
        atomic_write_json(staged / "manifest.json", manifest)
        planned = planned_commands(config, no_agent=no_agent)

        status = "succeeded"
        for index, command in enumerate(planned, start=1):
            argv = command["command"]
            try:
                validate_direct_command(command.get("policy_command", argv), config, allow_direct=bool(command.get("allow_direct")))
            except HeartbeatError as exc:
                launcher_info = command.get("launcher_info") if isinstance(command.get("launcher_info"), dict) else {}
                command_entries.append(
                    {
                        "id": command["id"],
                        "argv": argv,
                        **launcher_info,
                        "blocked": True,
                        "error": str(exc),
                        "finished_at": utc_now(),
                    }
                )
                status = "failed"
                break
            sidecar = staged / f"command-{index:02d}.json"
            entry = run_command(
                str(command["id"]),
                argv,
                cwd=target_root,
                timeout_seconds=int(command["timeout_seconds"]),
                sidecar_path=sidecar,
                launcher_info=command.get("launcher_info") if isinstance(command.get("launcher_info"), dict) else None,
            )
            command_entries.append(entry)
            if entry.get("returncode") != 0:
                status = "failed"
                break

        result = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "status": status,
            "target_root": str(target_root),
            "no_agent": no_agent,
            "command_count": len(command_entries),
            "recovered_before_run": recovered,
            "finished_at": utc_now(),
        }
        command_log = {"schema_version": SCHEMA_VERSION, "run_id": run_id, "commands": command_entries}
        manifest.update({"status": status, "finished_at": utc_now()})
        manifest = _finalize_staged(staged, manifest=manifest, result=result, command_log=command_log)
        latest = promote_staged_run(staged, state_root)
        active = state_root / ACTIVE_NAME
        if active.exists():
            active.unlink()
        return {
            "ok": status == "succeeded",
            "status": status,
            "run_id": run_id,
            "latest": latest,
            "state_root": str(state_root),
            "manifest": manifest,
            "result": result,
        }
    except Exception:
        if staged.exists() and staged.name.endswith(".staged"):
            try:
                manifest_path = staged / "manifest.json"
                manifest = {}
                if manifest_path.exists():
                    loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
                    manifest = loaded if isinstance(loaded, dict) else {}
                result = {
                    "schema_version": SCHEMA_VERSION,
                    "run_id": run_id,
                    "status": "failed",
                    "target_root": str(target_root),
                    "no_agent": no_agent,
                    "command_count": len(command_entries),
                    "finished_at": utc_now(),
                }
                command_log = {"schema_version": SCHEMA_VERSION, "run_id": run_id, "commands": command_entries}
                manifest.update({"schema_version": SCHEMA_VERSION, "run_id": run_id, "status": "failed", "finished_at": utc_now()})
                _finalize_staged(staged, manifest=manifest, result=result, command_log=command_log)
                promote_staged_run(staged, state_root)
            except Exception:
                pass
        raise
    finally:
        release_lock(state_root)


def status(*, target_root: Path, config_path: Path | None = None) -> dict[str, Any]:
    target_root = target_root.resolve()
    config_path = config_path or config_path_for(target_root)
    payload: dict[str, Any] = {
        "ok": True,
        "target_root": str(target_root),
        "config_path": str(config_path),
        "config_exists": config_path.is_file(),
    }
    if not config_path.is_file():
        payload.update({"enabled": False, "state_exists": False})
        return payload
    config = load_yaml(config_path)
    state_root = state_root_from_config(target_root, config)
    payload.update(
        {
            "enabled": heartbeat_enabled(config),
            "state_root": str(state_root),
            "state_exists": state_root.exists(),
            "locked": (state_root / LOCK_NAME).exists(),
        }
    )
    try:
        payload["latest"] = validate_latest_pointer(state_root) if state_root.exists() else None
        payload["active"] = validate_active_pointer(state_root) if state_root.exists() else None
    except HeartbeatError as exc:
        payload["ok"] = False
        payload.setdefault("issues", []).append(str(exc))
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Codex heartbeat harness.")
    parser.add_argument("--target-root", default=".", help="Target repository root.")
    parser.add_argument("--config", default=None, help="Path to config/codex_heartbeat.yaml.")
    parser.add_argument("--no-agent", action="store_true", help="Skip Codex model execution and exercise transactions only.")
    parser.add_argument("--force", action="store_true", help="Run even when heartbeat.enabled is false.")
    parser.add_argument("--status", action="store_true", help="Report status instead of running.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        target = Path(args.target_root).expanduser().resolve()
        config = Path(args.config).expanduser().resolve() if args.config else None
        payload = status(target_root=target, config_path=config) if args.status else run_once(
            target_root=target,
            config_path=config,
            no_agent=args.no_agent,
            force=args.force,
        )
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if payload.get("ok") else 1
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
