from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path


def project_environment_path(repo_root: Path) -> Path:
    return repo_root / ".venv"


def project_python(venv_path: Path) -> Path:
    candidate = venv_path / "bin" / "python"
    if candidate.exists():
        return candidate
    return venv_path / "Scripts" / "python.exe"


def inspect_environment(
    environment: Path,
    *,
    owner: str,
    ignored: bool,
    repair_hint: str,
) -> dict | None:
    if not (environment.exists() or environment.is_symlink()):
        return None
    label = owner.replace("_", " ")
    candidates = [
        environment / "bin" / "python",
        environment / "Scripts" / "python.exe",
    ]
    interpreter = next((path for path in candidates if path.exists() or path.is_symlink()), candidates[0])
    payload = {
        "path": str(environment),
        "owner": owner,
        "interpreter": str(interpreter),
        "ignored": ignored,
        "ok": True,
        "warnings": [],
        "repair_hints": [],
    }
    if environment.is_symlink() and not environment.exists():
        payload["ok"] = False
        payload["warnings"].append(f"{label} environment path is a broken symlink: {environment}")
        payload["repair_hints"].append(repair_hint)
        return payload
    pyvenv_cfg = environment / "pyvenv.cfg"
    if pyvenv_cfg.exists() or pyvenv_cfg.is_symlink():
        try:
            pyvenv_cfg.read_text(encoding="utf-8")
        except OSError as exc:
            payload["ok"] = False
            payload["warnings"].append(f"{label} pyvenv.cfg could not be read: {pyvenv_cfg}: {exc}")
    if not (interpreter.exists() or interpreter.is_symlink()):
        payload["ok"] = False
        payload["warnings"].append(f"{label} interpreter is missing: {interpreter}")
    else:
        try:
            stat_result = interpreter.stat()
            executable = interpreter.is_file() and os.access(interpreter, os.X_OK)
            payload["interpreter_executable"] = executable
            payload["interpreter_size"] = stat_result.st_size
        except OSError as exc:
            payload["ok"] = False
            payload["warnings"].append(f"{label} interpreter could not be inspected: {interpreter}: {exc}")
        else:
            if not executable:
                payload["ok"] = False
                payload["warnings"].append(f"{label} interpreter is not executable: {interpreter}")
    if not payload["ok"]:
        payload["repair_hints"].append(repair_hint)
    return payload


def legacy_environment_status(data_root: Path | None) -> dict | None:
    if data_root is None:
        return None
    legacy_environment = data_root / "venv"
    return inspect_environment(
        legacy_environment,
        owner="legacy_global_venv",
        ignored=True,
        repair_hint=(
            f"Remove or quarantine {legacy_environment}; run "
            "`./install --directory . --sync-env --non-interactive --yes` to quarantine it "
            "and rebuild the uv-managed source checkout .venv"
        ),
    )


def owned_environment_statuses(repo_root: Path, data_root: Path | None, target_root: Path | None) -> list[dict]:
    statuses: list[dict] = []
    source = inspect_environment(
        project_environment_path(repo_root),
        owner="source_venv",
        ignored=False,
        repair_hint=(
            f"Run `./install --directory {repo_root} --sync-env --non-interactive --yes` to quarantine "
            "and rebuild the uv-managed source checkout .venv"
        ),
    )
    if source:
        statuses.append(source)
    legacy = legacy_environment_status(data_root)
    if legacy:
        statuses.append(legacy)
    if target_root is not None:
        target_legacy = inspect_environment(
            target_root / ".localsetup" / "venv",
            owner="legacy_target_local_venv",
            ignored=True,
            repair_hint=(
                f"Run `./install --directory {repo_root} --target-directory {target_root} --sync-env --non-interactive --yes` "
                "to quarantine the legacy LocalSetup target-local venv"
            ),
        )
        if target_legacy:
            statuses.append(target_legacy)
    return statuses


def quarantine_root_for(environment: Path, repo_root: Path, data_root: Path | None, target_root: Path | None) -> Path:
    if environment == project_environment_path(repo_root):
        return repo_root / ".localsetup" / "state" / "dependency-repair"
    if data_root is not None and environment == data_root / "venv":
        return data_root / "state" / "dependency-repair"
    if target_root is not None and environment == target_root / ".localsetup" / "venv":
        return target_root / ".localsetup" / "state" / "dependency-repair"
    return repo_root / ".localsetup" / "state" / "dependency-repair"


def quarantine_environment(
    environment: Path,
    *,
    repo_root: Path,
    data_root: Path | None,
    target_root: Path | None,
    owner: str,
    reason: str,
    mode: str,
    uv_error: str | None = None,
) -> dict:
    quarantine_root = quarantine_root_for(environment, repo_root, data_root, target_root)
    quarantine_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base_name = f"{environment.name}-{stamp}"
    destination = quarantine_root / base_name
    index = 1
    while destination.exists() or destination.is_symlink():
        index += 1
        destination = quarantine_root / f"{base_name}-{index}"
    environment.rename(destination)
    record = {
        "original_path": str(environment),
        "quarantine_path": str(destination),
        "owner": owner,
        "reason": reason,
        "mode": mode,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uv_error": uv_error,
    }
    record_path = quarantine_root / f"{destination.name}.json"
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    record["record_path"] = str(record_path)
    return record
