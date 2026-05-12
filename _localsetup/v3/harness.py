from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml


HEARTBEAT_SKILL = "ls-codex-heartbeat"
HEARTBEAT_WORKFLOW = "ls-workflow-codex-heartbeat"
HEARTBEAT_TRIGGER_ID = "codex-heartbeat"
HEARTBEAT_TASK_ID = "codex-heartbeat-run"
HEARTBEAT_DOC = "HEARTBEAT.md"
HEARTBEAT_CONFIG = "config/codex_heartbeat.yaml"
CRON_MANIFEST = "cron/manifest.yaml"
CRON_OUTPUT = "cron/codex-heartbeat.crontab"


def _heartbeat_script(repo_root: Path) -> Path:
    return repo_root / "_localsetup" / "skills" / HEARTBEAT_SKILL / "scripts" / "codex_heartbeat.py"


def _cron_ctl(repo_root: Path) -> Path:
    return repo_root / "_localsetup" / "skills" / "ls-cron-orchestrator" / "scripts" / "cron_ctl.py"


def _template(repo_root: Path, name: str) -> Path:
    return repo_root / "_localsetup" / "skills" / HEARTBEAT_SKILL / "templates" / name


def _load_runtime(repo_root: Path) -> ModuleType:
    script = _heartbeat_script(repo_root)
    spec = importlib.util.spec_from_file_location("localsetup_codex_heartbeat_runtime", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load heartbeat runtime: {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return data


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    tmp.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    os.replace(tmp, path)


def _write_text_if_missing(path: Path, text: str) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def _target(target_root: Path | None, repo_root: Path) -> Path:
    return (target_root or repo_root).expanduser().resolve()


def _interval_schedule(minutes: int) -> str:
    if minutes < 1 or minutes > 1440:
        raise ValueError("heartbeat.interval_minutes must be in range 1..1440")
    return f"*/{minutes} * * * *" if minutes < 60 else "0 */1 * * *"


def _heartbeat_command(repo_root: Path, target_root: Path) -> list[str]:
    return [
        sys.executable,
        str((repo_root / "_localsetup" / "tools" / "localsetup_v3.py").resolve()),
        "--repo",
        str(repo_root.resolve()),
        "--target-directory",
        str(target_root.resolve()),
        "harness",
        "codex-heartbeat",
        "run",
        "--no-agent",
    ]


def _cron_task(repo_root: Path, target_root: Path, enabled: bool, timeout_seconds: int = 1800) -> dict[str, Any]:
    return {
        "id": HEARTBEAT_TASK_ID,
        "trigger": HEARTBEAT_TRIGGER_ID,
        "sequence_order": 100,
        "command": _heartbeat_command(repo_root, target_root),
        "enabled": enabled,
        "timeout_seconds": timeout_seconds,
    }


def _cron_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    tasks = manifest.get("tasks") if isinstance(manifest.get("tasks"), list) else []
    task = next((item for item in tasks if isinstance(item, dict) and item.get("id") == HEARTBEAT_TASK_ID), None)
    triggers = manifest.get("triggers") if isinstance(manifest.get("triggers"), dict) else {}
    return {
        "manifest_exists": bool(manifest),
        "trigger": triggers.get(HEARTBEAT_TRIGGER_ID),
        "task": task,
    }


def _upsert_cron_manifest(repo_root: Path, target_root: Path, config: dict[str, Any], *, enabled: bool) -> dict[str, Any]:
    manifest_path = target_root / CRON_MANIFEST
    manifest = _read_yaml(manifest_path)
    triggers = manifest.get("triggers")
    if not isinstance(triggers, dict):
        triggers = {}
    heartbeat = config.get("heartbeat") if isinstance(config.get("heartbeat"), dict) else {}
    interval = int(heartbeat.get("interval_minutes") or 15)
    triggers[HEARTBEAT_TRIGGER_ID] = {"schedule": _interval_schedule(interval)}
    manifest["triggers"] = triggers

    tasks = manifest.get("tasks")
    if not isinstance(tasks, list):
        tasks = []
    new_task = _cron_task(repo_root, target_root, enabled=enabled)
    replaced = False
    for index, task in enumerate(tasks):
        if isinstance(task, dict) and task.get("id") == HEARTBEAT_TASK_ID:
            tasks[index] = {**task, **new_task}
            replaced = True
            break
    if not replaced:
        tasks.append(new_task)
    manifest["tasks"] = tasks
    _write_yaml(manifest_path, manifest)
    validate_cron_manifest(repo_root, manifest_path)
    return {"path": str(manifest_path), "summary": _cron_summary(manifest)}


def validate_cron_manifest(repo_root: Path, manifest_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, str(_cron_ctl(repo_root)), "--manifest", str(manifest_path), "validate"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout).strip())


def _install_live_crontab(repo_root: Path, target_root: Path, *, yes: bool) -> dict[str, Any]:
    if not yes:
        raise RuntimeError("live crontab install requires --install-crontab and --yes")
    manifest = target_root / CRON_MANIFEST
    output = target_root / CRON_OUTPUT
    generate = subprocess.run(
        [
            sys.executable,
            str(_cron_ctl(repo_root)),
            "--manifest",
            str(manifest),
            "install",
            "--repo-root",
            str(target_root),
            "--output",
            str(output),
        ],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if generate.returncode != 0:
        raise RuntimeError((generate.stderr or generate.stdout).strip())
    install = subprocess.run(["crontab", str(output)], cwd=target_root, text=True, capture_output=True, check=False)
    if install.returncode != 0:
        raise RuntimeError((install.stderr or install.stdout).strip())
    return {"installed": True, "output": str(output)}


def _load_target_config(repo_root: Path, target_root: Path) -> dict[str, Any]:
    config_path = target_root / HEARTBEAT_CONFIG
    if not config_path.is_file():
        init(repo_root, target_root)
    return _read_yaml(config_path)


def plan(repo_root: Path, target_root: Path | None = None) -> dict[str, Any]:
    target = _target(target_root, repo_root)
    config_path = target / HEARTBEAT_CONFIG
    manifest_path = target / CRON_MANIFEST
    manifest = _read_yaml(manifest_path) if manifest_path.is_file() else {}
    runtime = _load_runtime(repo_root)
    status_payload = runtime.status(target_root=target, config_path=config_path) if config_path.exists() else {
        "ok": True,
        "config_exists": False,
        "enabled": False,
    }
    command_plan = runtime.plan_summary(target_root=target, config_path=config_path) if config_path.exists() else {
        "ok": True,
        "commands": [],
        "config_exists": False,
    }
    return {
        "ok": True,
        "target_root": str(target),
        "heartbeat_doc": str(target / HEARTBEAT_DOC),
        "config_path": str(config_path),
        "cron_manifest": str(manifest_path),
        "state_dir": str(target / "state" / "codex-heartbeat"),
        "launcher_command": _heartbeat_command(repo_root, target),
        "command_plan": command_plan,
        "status": status_payload,
        "cron": _cron_summary(manifest),
    }


def init(repo_root: Path, target_root: Path | None = None) -> dict[str, Any]:
    target = _target(target_root, repo_root)
    doc_created = _write_text_if_missing(target / HEARTBEAT_DOC, _template(repo_root, "HEARTBEAT.md").read_text(encoding="utf-8"))
    config_created = _write_text_if_missing(
        target / HEARTBEAT_CONFIG,
        _template(repo_root, "codex_heartbeat.yaml").read_text(encoding="utf-8"),
    )
    return {
        "ok": True,
        "target_root": str(target),
        "created": {
            HEARTBEAT_DOC: doc_created,
            HEARTBEAT_CONFIG: config_created,
        },
        "status": plan(repo_root, target)["status"],
    }


def enable(
    repo_root: Path,
    target_root: Path | None = None,
    *,
    install_crontab: bool = False,
    yes: bool = False,
) -> dict[str, Any]:
    if install_crontab and not yes:
        raise RuntimeError("live crontab install requires --install-crontab and --yes")
    target = _target(target_root, repo_root)
    config = _load_target_config(repo_root, target)
    heartbeat = config.setdefault("heartbeat", {})
    if not isinstance(heartbeat, dict):
        raise ValueError("heartbeat config must be a mapping")
    heartbeat["enabled"] = True
    _write_yaml(target / HEARTBEAT_CONFIG, config)
    cron = _upsert_cron_manifest(repo_root, target, config, enabled=True)
    crontab = _install_live_crontab(repo_root, target, yes=yes) if install_crontab else {"installed": False}
    return {"ok": True, "target_root": str(target), "enabled": True, "cron": cron, "crontab": crontab}


def disable(
    repo_root: Path,
    target_root: Path | None = None,
    *,
    install_crontab: bool = False,
    yes: bool = False,
) -> dict[str, Any]:
    if install_crontab and not yes:
        raise RuntimeError("live crontab install requires --install-crontab and --yes")
    target = _target(target_root, repo_root)
    config = _load_target_config(repo_root, target)
    heartbeat = config.setdefault("heartbeat", {})
    if not isinstance(heartbeat, dict):
        raise ValueError("heartbeat config must be a mapping")
    heartbeat["enabled"] = False
    _write_yaml(target / HEARTBEAT_CONFIG, config)
    cron = _upsert_cron_manifest(repo_root, target, config, enabled=False)
    crontab = _install_live_crontab(repo_root, target, yes=yes) if install_crontab else {"installed": False}
    return {"ok": True, "target_root": str(target), "enabled": False, "cron": cron, "crontab": crontab}


def status(repo_root: Path, target_root: Path | None = None) -> dict[str, Any]:
    target = _target(target_root, repo_root)
    runtime = _load_runtime(repo_root)
    payload = runtime.status(target_root=target, config_path=target / HEARTBEAT_CONFIG)
    manifest_path = target / CRON_MANIFEST
    payload["cron"] = _cron_summary(_read_yaml(manifest_path) if manifest_path.is_file() else {})
    return payload


def run(
    repo_root: Path,
    target_root: Path | None = None,
    *,
    no_agent: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    target = _target(target_root, repo_root)
    runtime = _load_runtime(repo_root)
    return runtime.run_once(target_root=target, config_path=target / HEARTBEAT_CONFIG, no_agent=no_agent, force=force)


def payload_to_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)
