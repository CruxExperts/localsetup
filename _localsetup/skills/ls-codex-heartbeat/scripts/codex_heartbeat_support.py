"""Support helpers for the Codex heartbeat runtime."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - checked by the caller in normal use
    yaml = None

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
    resolved = shutil.which(argv[0], path=path_env)
    if not resolved:
        raise HeartbeatError(f"unable to resolve agent profile executable: {argv[0]}")
    return [resolved, *argv[1:]], resolved


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
    info: dict[str, Any] = {
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
        info["resolved_executable"] = str(Path(command[0]).resolve()) if Path(command[0]).is_absolute() else None
    elif launcher == "resolved-path":
        command, resolved = _resolve_profile_executable(profile, logical_argv)
        info["resolved_executable"] = resolved
    elif launcher == "shell-login":
        command, rendered = _shell_login_command(profile, logical_argv)
        info["rendered_command"] = command[-1]
        info["resolved_executable"] = None
    else:
        raise HeartbeatError("agent profile launcher must be one of: direct-argv, resolved-path, shell-login")
    return {
        "id": f"{profile_name}-agent",
        "command": command,
        "policy_command": logical_argv,
        "timeout_seconds": timeout_seconds,
        "allow_direct": bool(codex.get("allow_direct", profile.get("allow_direct", False))),
        "launcher_info": info,
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
