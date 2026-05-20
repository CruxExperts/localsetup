from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
from typing import Callable, Sequence


Runner = Callable[..., subprocess.CompletedProcess[str]]

MIN_UV_VERSION = "0.4.27"
ACTIVE_DEPENDENCY_MODES = {"uv-sync", "prompt-only"}
LEGACY_DEPENDENCY_MODE_ALIASES = {"managed-venv": "uv-sync", "user-pip": "prompt-only"}
ACCEPTED_DEPENDENCY_MODES = ACTIVE_DEPENDENCY_MODES | set(LEGACY_DEPENDENCY_MODE_ALIASES)


@dataclass(frozen=True)
class DependencyStatus:
    mode: str
    dependency_manager: str
    project_root: str
    pyproject: str
    lockfile: str
    environment_path: str
    interpreter: str | None
    uv_path: str | None
    uv_version: str | None
    minimum_version: str
    lock_status: str
    sync_status: str
    offline: bool
    bootstrap_attempted: bool
    bootstrap_source: str | None
    legacy_flag_used: bool
    warnings: list[str]
    blockers: list[str]
    recoverable_next_steps: list[str]
    commands: list[list[str]]
    ok: bool

    def to_dict(self) -> dict:
        sync_command = next((cmd for cmd in self.commands if "sync" in cmd), None)
        run_command = next((cmd for cmd in self.commands if "run" in cmd), None)
        return {
            "mode": self.mode,
            "dependency_manager": self.dependency_manager,
            "project_root": self.project_root,
            "pyproject": self.pyproject,
            "lockfile": self.lockfile,
            "environment_path": self.environment_path,
            "interpreter": self.interpreter,
            "uv_path": self.uv_path,
            "uv_version": self.uv_version,
            "minimum_version": self.minimum_version,
            "lock_status": self.lock_status,
            "sync_status": self.sync_status,
            "offline": self.offline,
            "bootstrap_attempted": self.bootstrap_attempted,
            "bootstrap_source": self.bootstrap_source,
            "legacy_flag_used": self.legacy_flag_used,
            "warnings": self.warnings,
            "blockers": self.blockers,
            "recoverable_next_steps": self.recoverable_next_steps,
            "commands": self.commands,
            "sync_command": sync_command,
            "run_command": run_command,
            "ok": self.ok,
        }


def normalize_dependency_mode(mode: str | None) -> str:
    selected = mode or "uv-sync"
    return LEGACY_DEPENDENCY_MODE_ALIASES.get(selected, selected)


def dependency_mode_warning(mode: str | None) -> str | None:
    if mode in LEGACY_DEPENDENCY_MODE_ALIASES:
        replacement = LEGACY_DEPENDENCY_MODE_ALIASES[mode]
        return f"dependency mode `{mode}` is deprecated; using `{replacement}`"
    return None


def pyproject_path(repo_root: Path) -> Path:
    return repo_root / "pyproject.toml"


def uv_lock_path(repo_root: Path) -> Path:
    return repo_root / "uv.lock"


def project_environment_path(repo_root: Path) -> Path:
    return repo_root / ".venv"


def project_python(venv_path: Path) -> Path:
    candidate = venv_path / "bin" / "python"
    if candidate.exists():
        return candidate
    return venv_path / "Scripts" / "python.exe"


def file_sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(
    cmd: Sequence[str],
    *,
    cwd: Path | None = None,
    runner: Runner | None = None,
) -> subprocess.CompletedProcess[str]:
    run = runner or subprocess.run
    return run(list(cmd), cwd=str(cwd) if cwd else None, text=True, capture_output=True, check=False)


def _offline_requested() -> bool:
    return os.environ.get("LOCALSETUP_UV_OFFLINE") == "1" or os.environ.get("UV_OFFLINE") == "1"


def _uv_binary() -> str | None:
    configured = os.environ.get("LOCALSETUP_UV_BIN")
    if configured:
        return configured
    return shutil.which("uv")


def _parse_uv_version(output: str) -> str | None:
    match = re.search(r"\b(\d+\.\d+\.\d+)(?:[-+][^\s]+)?", output)
    return match.group(1) if match else None


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _version_at_least(version: str, minimum: str) -> bool:
    return _version_tuple(version) >= _version_tuple(minimum)


def _uv_project_command(repo_root: Path, uv_bin: str | None, args: list[str], *, offline: bool) -> list[str]:
    base = [uv_bin or "uv"]
    if offline:
        base.append("--offline")
    base.extend(["--project", str(repo_root), *args])
    return base


def _command_text(command: Sequence[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def uv_lock_metadata(repo_root: Path, *, lock_status: str | None = None) -> dict:
    pyproject = pyproject_path(repo_root)
    lockfile = uv_lock_path(repo_root)
    metadata = {
        "dependency_manager": "uv",
        "pyproject": str(pyproject),
        "pyproject_sha256": file_sha256(pyproject) if pyproject.exists() else None,
        "lockfile": str(lockfile),
        "lockfile_sha256": file_sha256(lockfile) if lockfile.exists() else None,
        "lock_status": lock_status,
        "hash_mode": lockfile.exists(),
    }
    return metadata


def _classify_sync_failure(text: str) -> str:
    lowered = text.lower()
    if "offline" in lowered or "network disabled" in lowered:
        return "offline-cache-miss"
    if "certificate" in lowered or "tls" in lowered or "ssl" in lowered:
        return "tls-or-certificate"
    if "network" in lowered or "connection" in lowered or "timed out" in lowered:
        return "network-or-index"
    if "lock" in lowered and ("out-of-date" in lowered or "stale" in lowered or "would change" in lowered):
        return "stale-lockfile"
    if "resolution" in lowered or "solve" in lowered or "no solution" in lowered:
        return "dependency-resolution"
    return "uv-sync"


def tool_status(name: str) -> dict:
    path = shutil.which(name)
    return {"name": name, "path": path, "ok": path is not None}


def dependency_status(
    repo_root: Path,
    *,
    mode: str = "uv-sync",
    data_root: Path | None = None,
    runner: Runner | None = None,
) -> DependencyStatus:
    del data_root
    raw_mode = mode
    canonical_mode = normalize_dependency_mode(mode)
    warnings: list[str] = []
    blockers: list[str] = []
    recoverable_next_steps: list[str] = []
    legacy_warning = dependency_mode_warning(raw_mode)
    if legacy_warning:
        warnings.append(legacy_warning)
    legacy_flag_used = os.environ.get("LOCALSETUP_LEGACY_INSTALL_DEPS") == "1"
    if legacy_flag_used:
        warnings.append("`--install-deps` is deprecated; use `--sync-env` for uv-managed dependency sync")

    pyproject = pyproject_path(repo_root)
    lockfile = uv_lock_path(repo_root)
    environment = project_environment_path(repo_root)
    interpreter = project_python(environment) if environment.exists() else None
    offline = _offline_requested()
    uv_bin = _uv_binary()
    uv_version: str | None = None
    lock_status = "unchecked"

    commands = [
        _uv_project_command(repo_root, uv_bin, ["lock", "--check"], offline=offline),
        _uv_project_command(repo_root, uv_bin, ["sync", "--locked", "--no-dev"], offline=offline),
        _uv_project_command(repo_root, uv_bin, ["run", "--locked"], offline=offline),
    ]

    if canonical_mode not in ACTIVE_DEPENDENCY_MODES:
        blockers.append(f"unsupported dependency mode: {raw_mode}")
    if not pyproject.exists():
        blockers.append(f"pyproject.toml not found: {pyproject}")
    if not lockfile.exists():
        blockers.append(f"uv.lock not found: {lockfile}")
        lock_status = "missing"

    if not uv_bin:
        blockers.append("uv is required for Localsetup dependency sync but was not found on PATH")
        recoverable_next_steps.append("Install uv, or set LOCALSETUP_UV_BIN to a preinstalled uv binary")
    else:
        try:
            version_result = _run([uv_bin, "--version"], runner=runner)
        except OSError as exc:
            version_result = None
            blockers.append(f"uv version check failed: {exc}")
            recoverable_next_steps.append("Install uv, or set LOCALSETUP_UV_BIN to a preinstalled uv binary")
        if version_result is None:
            pass
        elif version_result.returncode != 0:
            blockers.append(f"uv version check failed: {version_result.stderr.strip() or version_result.stdout.strip()}")
        else:
            uv_version = _parse_uv_version(version_result.stdout)
            if not uv_version:
                blockers.append(f"uv version output was not recognized: {version_result.stdout.strip()}")
            elif not _version_at_least(uv_version, MIN_UV_VERSION):
                blockers.append(f"uv {uv_version} is too old; Localsetup requires uv >= {MIN_UV_VERSION}")
                recoverable_next_steps.append("Upgrade uv, then rerun `uv lock --check` and `uv sync --locked --no-dev`")

    can_check_lock = (
        uv_bin
        and uv_version
        and _version_at_least(uv_version, MIN_UV_VERSION)
        and lockfile.exists()
        and pyproject.exists()
    )
    if can_check_lock:
        try:
            check = _run(commands[0], cwd=repo_root, runner=runner)
        except OSError as exc:
            check = None
            blockers.append(f"uv lock check failed: {exc}")
            recoverable_next_steps.append("Install uv, or set LOCALSETUP_UV_BIN to a preinstalled uv binary")
        if check is None:
            pass
        elif check.returncode == 0:
            lock_status = "current"
        else:
            lock_status = "stale"
            detail = check.stderr.strip() or check.stdout.strip()
            blockers.append(f"uv lockfile is stale or invalid: {detail}")
            recoverable_next_steps.append("Run `uv lock` after updating pyproject.toml, then commit uv.lock")

    return DependencyStatus(
        mode=canonical_mode,
        dependency_manager="uv",
        project_root=str(repo_root),
        pyproject=str(pyproject),
        lockfile=str(lockfile),
        environment_path=str(environment),
        interpreter=str(interpreter) if interpreter and interpreter.exists() else None,
        uv_path=uv_bin,
        uv_version=uv_version,
        minimum_version=MIN_UV_VERSION,
        lock_status=lock_status,
        sync_status="not-run",
        offline=offline,
        bootstrap_attempted=os.environ.get("LOCALSETUP_UV_BOOTSTRAP_ATTEMPTED") == "1",
        bootstrap_source=os.environ.get("LOCALSETUP_UV_BOOTSTRAP_SOURCE"),
        legacy_flag_used=legacy_flag_used,
        warnings=warnings,
        blockers=blockers,
        recoverable_next_steps=recoverable_next_steps,
        commands=commands,
        ok=not blockers,
    )


def ensure_dependencies(
    repo_root: Path,
    *,
    mode: str = "uv-sync",
    data_root: Path | None = None,
    runner: Runner | None = None,
) -> dict:
    status = dependency_status(repo_root, mode=mode, data_root=data_root, runner=runner)
    if status.mode == "prompt-only":
        return status.to_dict() | {
            "changed": False,
            "lock": uv_lock_metadata(repo_root, lock_status=status.lock_status),
        }
    if status.blockers:
        steps = "; ".join(status.recoverable_next_steps)
        suffix = f" Next steps: {steps}" if steps else ""
        raise RuntimeError("; ".join(status.blockers) + suffix)
    if os.environ.get("LOCALSETUP_UV_ALREADY_SYNCED") == "1":
        payload = status.to_dict()
        payload.update(
            {
                "changed": False,
                "sync_status": "success",
                "sync_stdout": "",
                "lock": uv_lock_metadata(repo_root, lock_status=status.lock_status),
            }
        )
        return payload

    sync_command = next(cmd for cmd in status.commands if "sync" in cmd)
    try:
        sync = _run(sync_command, cwd=repo_root, runner=runner)
    except OSError as exc:
        raise RuntimeError(
            f"uv sync failed (missing-uv): {exc}. Command: {_command_text(sync_command)}"
        ) from exc
    if sync.returncode != 0:
        output = sync.stderr.strip() or sync.stdout.strip()
        category = _classify_sync_failure(output)
        raise RuntimeError(
            f"uv sync failed ({category}): {output}. Command: {_command_text(sync_command)}"
        )

    refreshed = dependency_status(repo_root, mode=status.mode, data_root=data_root, runner=runner)
    payload = refreshed.to_dict()
    payload.update(
        {
            "changed": True,
            "sync_status": "success",
            "sync_stdout": sync.stdout.strip(),
            "lock": uv_lock_metadata(repo_root, lock_status=refreshed.lock_status),
        }
    )
    return payload
