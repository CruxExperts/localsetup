#!/usr/bin/env python3
"""Codex heartbeat harness runtime with atomic run artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover - surfaced as a CLI error when config is loaded.
    yaml = None  # type: ignore[assignment]


SCHEMA_VERSION = "1.0"
STATE_DIR_DEFAULT = ".localsetup/state/codex-heartbeat"
LOCK_NAME = "heartbeat.lock"
ACTIVE_NAME = "active.json"
LATEST_NAME = "latest.json"
RUNS_DIR_NAME = "runs"
MAX_TAIL_CHARS = 12000
DEFAULT_COMMAND_TIMEOUT = 300
MAX_COMMAND_TIMEOUT = 86400

BLOCKED_GIT_SUBCOMMANDS = {"commit", "push"}
BLOCKED_EXECUTABLES = {
    "dd",
    "chmod",
    "chown",
    "docker",
    "mkfs",
    "mount",
    "mv",
    "podman",
    "umount",
    "kubectl",
    "rm",
    "rmdir",
    "shutdown",
    "reboot",
    "poweroff",
    "systemctl",
    "service",
}


class HeartbeatError(RuntimeError):
    """Raised for recoverable harness errors."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def sha256_json(payload: Any) -> str:
    return sha256_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def load_yaml(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise HeartbeatError("PyYAML is required to read codex_heartbeat.yaml")
    if not path.is_file():
        raise HeartbeatError(f"config not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise HeartbeatError("config root must be a mapping")
    return data


def config_path_for(target_root: Path) -> Path:
    return target_root / "config" / "codex_heartbeat.yaml"


def state_root_from_config(target_root: Path, config: dict[str, Any]) -> Path:
    heartbeat = config.get("heartbeat") if isinstance(config.get("heartbeat"), dict) else {}
    raw = str(heartbeat.get("state_dir") or STATE_DIR_DEFAULT)
    path = Path(raw).expanduser()
    if path.is_absolute():
        raise HeartbeatError("heartbeat.state_dir must be repo-relative")
    resolved = (target_root / path).resolve()
    try:
        resolved.relative_to(target_root.resolve())
    except ValueError as exc:
        raise HeartbeatError("heartbeat.state_dir must stay inside the target repository") from exc
    return resolved


def heartbeat_enabled(config: dict[str, Any]) -> bool:
    heartbeat = config.get("heartbeat") if isinstance(config.get("heartbeat"), dict) else {}
    return bool(heartbeat.get("enabled", False))


def command_policy(config: dict[str, Any]) -> dict[str, Any]:
    policy = config.get("direct_command_policy") if isinstance(config.get("direct_command_policy"), dict) else {}
    allowlist = policy.get("allowlist") if isinstance(policy.get("allowlist"), list) else []
    return {
        "allow_destructive": bool(policy.get("allow_destructive", False)),
        "allow_git_writes": bool(policy.get("allow_git_writes", False)),
        "allowlist": {str(item).strip() for item in allowlist if str(item).strip()},
    }


def _command_key(argv: list[str]) -> str:
    return " ".join(argv)


def validate_direct_command(argv: list[str], config: dict[str, Any], *, allow_direct: bool = False) -> None:
    if not argv:
        raise HeartbeatError("command argv must not be empty")
    policy = command_policy(config)
    key = _command_key(argv)
    if allow_direct or key in policy["allowlist"]:
        return
    executable = Path(argv[0]).name
    if executable == "git" and len(argv) > 1 and argv[1] in BLOCKED_GIT_SUBCOMMANDS and not policy["allow_git_writes"]:
        raise HeartbeatError(f"direct command policy blocked git {argv[1]}")
    if executable in BLOCKED_EXECUTABLES and not policy["allow_destructive"]:
        raise HeartbeatError(f"direct command policy blocked destructive executable: {executable}")


def normalize_timeout(value: Any) -> int:
    if value is None:
        return DEFAULT_COMMAND_TIMEOUT
    try:
        timeout = int(value)
    except (TypeError, ValueError) as exc:
        raise HeartbeatError("timeout_seconds must be an integer") from exc
    if timeout < 1 or timeout > MAX_COMMAND_TIMEOUT:
        raise HeartbeatError(f"timeout_seconds must be in range 1..{MAX_COMMAND_TIMEOUT}")
    return timeout


def _tail(text: str) -> str:
    return text[-MAX_TAIL_CHARS:]


def run_command(
    command_id: str,
    argv: list[str],
    *,
    cwd: Path,
    timeout_seconds: int,
    sidecar_path: Path,
    launcher_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started = utc_now()
    entry: dict[str, Any] = {
        "id": command_id,
        "argv": argv,
        "cwd": str(cwd),
        "started_at": started,
        "timeout_seconds": timeout_seconds,
    }
    if launcher_info:
        entry.update(launcher_info)
    proc: subprocess.Popen[str] | None = None
    try:
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            shell=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        entry["pid"] = proc.pid
        try:
            entry["pgid"] = os.getpgid(proc.pid)
            entry["sid"] = os.getsid(proc.pid)
        except OSError:
            pass
        try:
            stdout, stderr = proc.communicate(timeout=timeout_seconds)
            entry["returncode"] = proc.returncode
            entry["timed_out"] = False
        except subprocess.TimeoutExpired:
            entry["timed_out"] = True
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except OSError:
                proc.terminate()
            try:
                stdout, stderr = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except OSError:
                    proc.kill()
                stdout, stderr = proc.communicate()
            entry["returncode"] = 124
        entry["stdout_tail"] = _tail(stdout or "")
        entry["stderr_tail"] = _tail(stderr or "")
        entry["finished_at"] = utc_now()
    except Exception as exc:
        entry.update(
            {
                "returncode": 1,
                "timed_out": False,
                "error": f"{type(exc).__name__}: {exc}",
                "finished_at": utc_now(),
            }
        )
    atomic_write_json(sidecar_path, entry)
    entry["sidecar"] = sidecar_path.name
    entry["sidecar_sha256"] = sha256_file(sidecar_path)
    return entry


def load_hooks(config: dict[str, Any], name: str) -> list[dict[str, Any]]:
    hooks = config.get("hooks") if isinstance(config.get("hooks"), dict) else {}
    raw = hooks.get(name) if isinstance(hooks.get(name), list) else []
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise HeartbeatError(f"hooks.{name}[{index}] must be a mapping")
        command = item.get("command")
        if not isinstance(command, list) or not command or not all(isinstance(part, str) and part for part in command):
            raise HeartbeatError(f"hooks.{name}[{index}].command must be a non-empty argv list")
        normalized.append(
            {
                "id": str(item.get("id") or f"{name}-{index + 1}"),
                "command": command,
                "launcher_mode": "direct-argv",
                "timeout_seconds": normalize_timeout(item.get("timeout_seconds")),
                "allow_direct": bool(item.get("allow_direct", False)),
            }
        )
    return normalized


def _agent_profile(config: dict[str, Any], profile_name: str) -> dict[str, Any]:
    profiles = config.get("agent_profiles") if isinstance(config.get("agent_profiles"), dict) else {}
    profile = profiles.get(profile_name)
    if not isinstance(profile, dict):
        raise HeartbeatError(f"agent profile not found: {profile_name}")
    return profile


def _path_env(profile: dict[str, Any]) -> str | None:
    raw_path = profile.get("path_env")
    if isinstance(raw_path, str) and raw_path.strip():
        return raw_path
    path_entries = profile.get("path")
    if isinstance(path_entries, list):
        entries = [str(item) for item in path_entries if str(item).strip()]
        if entries:
            return os.pathsep.join(entries)
    return None


def _profile_prompt(profile: dict[str, Any]) -> str:
    prompt = profile.get("prompt")
    if isinstance(prompt, str) and prompt.strip():
        return prompt
    return "Read HEARTBEAT.md, inspect queued heartbeat work, and produce a concise status report."


def _profile_command_argv(profile: dict[str, Any]) -> list[str]:
    command = profile.get("command")
    if isinstance(command, list) and command and all(isinstance(part, str) and part for part in command):
        return list(command)
    command_name = str(profile.get("command_name") or "codex").strip()
    if not command_name:
        raise HeartbeatError("agent profile command_name must not be empty")
    argv = [command_name, "exec"]
    model = profile.get("model")
    if isinstance(model, str) and model.strip():
        argv.extend(["--model", model.strip()])
    reasoning_effort = profile.get("reasoning_effort")
    if isinstance(reasoning_effort, str) and reasoning_effort.strip():
        argv.extend(["-c", f'model_reasoning_effort="{reasoning_effort.strip()}"'])
    sandbox = profile.get("sandbox")
    if isinstance(sandbox, str) and sandbox.strip():
        argv.extend(["--sandbox", sandbox.strip()])
    if bool(profile.get("json", False)):
        argv.append("--json")
    argv.extend(["--", _profile_prompt(profile)])
    return argv


def _resolve_profile_executable(profile: dict[str, Any], argv: list[str]) -> tuple[list[str], str]:
    path_env = _path_env(profile)
    executable = shutil.which(argv[0], path=path_env)
    if not executable:
        raise HeartbeatError(f"unable to resolve agent profile executable: {argv[0]}")
    return [executable, *argv[1:]], executable


def _shell_login_command(profile: dict[str, Any], argv: list[str]) -> tuple[list[str], str]:
    shell_path = str(profile.get("shell") or "/bin/bash")
    if not Path(shell_path).is_absolute():
        resolved_shell = shutil.which(shell_path)
        if not resolved_shell:
            raise HeartbeatError(f"unable to resolve shell-login shell: {shell_path}")
        shell_path = resolved_shell
    rendered = shlex.join(argv)
    path_env = _path_env(profile)
    if path_env:
        rendered = f"PATH={shlex.quote(path_env)}; export PATH; {rendered}"
    return [shell_path, "-lc", rendered], rendered


def _codex_profile_command(config: dict[str, Any], codex: dict[str, Any]) -> dict[str, Any] | None:
    profile_name = str(codex.get("profile") or "heartbeat")
    profiles = config.get("agent_profiles") if isinstance(config.get("agent_profiles"), dict) else {}
    if profile_name not in profiles:
        return None
    profile = _agent_profile(config, profile_name)
    launcher = str(profile.get("launcher") or "resolved-path").strip()
    logical_argv = _profile_command_argv(profile)
    timeout_seconds = normalize_timeout(codex.get("timeout_seconds", profile.get("timeout_seconds")))
    model = profile.get("model")
    launcher_info: dict[str, Any] = {
        "launcher_mode": launcher,
        "profile": profile_name,
        "app": str(profile.get("app") or "codex"),
        "model_policy": str(profile.get("model_policy") or "configurable"),
        "model": model if isinstance(model, str) and model.strip() else None,
        "reasoning_effort": profile.get("reasoning_effort"),
        "json": bool(profile.get("json", False)),
        "logical_argv": logical_argv,
    }
    command = logical_argv
    if launcher == "direct-argv":
        launcher_info["resolved_executable"] = str(Path(command[0]).resolve()) if Path(command[0]).is_absolute() else None
    elif launcher == "resolved-path":
        command, resolved = _resolve_profile_executable(profile, logical_argv)
        launcher_info["resolved_executable"] = resolved
    elif launcher == "shell-login":
        command, rendered = _shell_login_command(profile, logical_argv)
        launcher_info["rendered_command"] = rendered
        launcher_info["resolved_executable"] = None
    else:
        raise HeartbeatError("agent profile launcher must be one of: direct-argv, resolved-path, shell-login")
    return {
        "id": f"{profile_name}-agent",
        "command": command,
        "policy_command": logical_argv,
        "timeout_seconds": timeout_seconds,
        "allow_direct": bool(codex.get("allow_direct", profile.get("allow_direct", False))),
        "launcher_info": launcher_info,
    }


def load_codex_command(config: dict[str, Any]) -> dict[str, Any] | None:
    codex = config.get("codex") if isinstance(config.get("codex"), dict) else {}
    if not bool(codex.get("enabled", False)):
        return None
    profile_command = _codex_profile_command(config, codex)
    if profile_command:
        return profile_command
    command = codex.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(part, str) and part for part in command):
        raise HeartbeatError("codex.command must be a non-empty argv list when codex.enabled is true")
    return {
        "id": "codex-agent",
        "command": command,
        "policy_command": command,
        "launcher_info": {
            "launcher_mode": "direct-argv",
            "profile": None,
            "app": "codex",
            "model_policy": "legacy-command",
            "model": codex.get("model") if isinstance(codex.get("model"), str) else None,
            "logical_argv": command,
            "resolved_executable": str(Path(command[0]).resolve()) if Path(command[0]).is_absolute() else None,
        },
        "timeout_seconds": normalize_timeout(codex.get("timeout_seconds")),
        "allow_direct": bool(codex.get("allow_direct", False)),
    }


def planned_commands(config: dict[str, Any], *, no_agent: bool = False) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    commands.extend(load_hooks(config, "before"))
    codex_command = load_codex_command(config)
    if codex_command and not no_agent:
        commands.append(codex_command)
    commands.extend(load_hooks(config, "after"))
    return commands


def plan_summary(*, target_root: Path, config_path: Path | None = None, no_agent: bool = False) -> dict[str, Any]:
    target_root = target_root.resolve()
    config_path = config_path or config_path_for(target_root)
    if not config_path.is_file():
        return {"ok": True, "commands": [], "config_exists": False}
    config = load_yaml(config_path)
    summaries: list[dict[str, Any]] = []
    try:
        planned = planned_commands(config, no_agent=no_agent)
    except HeartbeatError as exc:
        return {"ok": False, "commands": [], "config_exists": True, "error": str(exc)}
    for command in planned:
        info = command.get("launcher_info") if isinstance(command.get("launcher_info"), dict) else {}
        summaries.append(
            {
                "id": command["id"],
                "argv": command["command"],
                "policy_argv": command.get("policy_command", command["command"]),
                "launcher_mode": info.get("launcher_mode", command.get("launcher_mode", "direct-argv")),
                "resolved_executable": info.get("resolved_executable"),
                "rendered_command": info.get("rendered_command"),
                "model_policy": info.get("model_policy"),
                "model": info.get("model"),
                "timeout_seconds": command["timeout_seconds"],
            }
        )
    return {"ok": True, "commands": summaries, "config_exists": True}


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
