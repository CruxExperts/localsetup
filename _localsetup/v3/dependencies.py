from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from importlib import metadata
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Callable, Sequence


Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class DependencyStatus:
    mode: str
    requirements: str
    venv_path: str | None
    interpreter: str | None
    missing: list[str]
    warnings: list[str]
    commands: list[list[str]]
    ok: bool

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "requirements": self.requirements,
            "venv_path": self.venv_path,
            "interpreter": self.interpreter,
            "missing": self.missing,
            "warnings": self.warnings,
            "commands": self.commands,
            "ok": self.ok,
        }


def requirements_path(repo_root: Path) -> Path:
    return repo_root / "_localsetup" / "requirements.txt"


def managed_venv_path(repo_root: Path, data_root: Path | None = None) -> Path:
    root = data_root if data_root is not None else repo_root / ".localsetup"
    return root / "venv"


def venv_python(venv_path: Path) -> Path:
    candidate = venv_path / "bin" / "python"
    if candidate.exists():
        return candidate
    return venv_path / "Scripts" / "python.exe"


def _run(cmd: Sequence[str], runner: Runner | None = None) -> subprocess.CompletedProcess[str]:
    run = runner or subprocess.run
    return run(list(cmd), text=True, capture_output=True, check=False)


def _requirement_names(path: Path) -> list[str]:
    if not path.exists():
        return []
    names: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith(("-", "git+", "http://", "https://")):
            continue
        for marker in ["==", ">=", "<=", "~=", "!=", ">", "<", "["]:
            if marker in line:
                line = line.split(marker, 1)[0]
                break
        name = line.strip().replace("_", "-")
        if name:
            names.append(name)
    return names


def missing_requirements(req_path: Path) -> list[str]:
    missing: list[str] = []
    for name in _requirement_names(req_path):
        try:
            metadata.version(name)
        except metadata.PackageNotFoundError:
            missing.append(name)
    return missing


def has_venv_module() -> bool:
    return importlib.util.find_spec("venv") is not None


def pip_available(python: str | Path = sys.executable, runner: Runner | None = None) -> bool:
    result = _run([str(python), "-m", "pip", "--version"], runner=runner)
    return result.returncode == 0


def dependency_status(
    repo_root: Path,
    *,
    mode: str = "managed-venv",
    data_root: Path | None = None,
    runner: Runner | None = None,
) -> DependencyStatus:
    req = requirements_path(repo_root)
    venv_path = managed_venv_path(repo_root, data_root)
    interpreter = venv_python(venv_path) if venv_path.exists() else None
    warnings: list[str] = []
    commands: list[list[str]] = []
    missing = missing_requirements(req)

    if not req.exists():
        warnings.append(f"missing requirements file: {req}")
    if mode == "managed-venv":
        commands = [
            [sys.executable, "-m", "venv", str(venv_path)],
            [str(venv_python(venv_path)), "-m", "pip", "install", "-r", str(req)],
            [str(venv_python(venv_path)), "-m", "pip", "check"],
        ]
        if not has_venv_module():
            warnings.append("python venv module is unavailable; install python3-venv for this interpreter")
        if interpreter is not None and not pip_available(interpreter, runner=runner):
            warnings.append(f"pip is unavailable inside managed venv: {interpreter}")
        ok = bool(req.exists()) and has_venv_module() and (interpreter is None or pip_available(interpreter, runner=runner))
    elif mode == "user-pip":
        commands = [[sys.executable, "-m", "pip", "install", "--user", "-r", str(req)], [sys.executable, "-m", "pip", "check"]]
        if not pip_available(sys.executable, runner=runner):
            warnings.append("pip is unavailable for the current interpreter")
        ok = bool(req.exists()) and pip_available(sys.executable, runner=runner)
    else:
        commands = [[sys.executable, "-m", "venv", str(venv_path)]]
        ok = not missing

    return DependencyStatus(
        mode=mode,
        requirements=str(req),
        venv_path=str(venv_path) if mode in {"managed-venv", "prompt-only"} else None,
        interpreter=str(interpreter) if interpreter else None,
        missing=missing,
        warnings=warnings,
        commands=commands,
        ok=ok and not (mode == "prompt-only" and missing),
    )


def ensure_dependencies(
    repo_root: Path,
    *,
    mode: str = "managed-venv",
    data_root: Path | None = None,
    runner: Runner | None = None,
) -> dict:
    req = requirements_path(repo_root)
    if mode == "prompt-only":
        status = dependency_status(repo_root, mode=mode, data_root=data_root, runner=runner)
        return status.to_dict() | {"changed": False, "pip_check": None}

    if mode == "user-pip":
        if not pip_available(sys.executable, runner=runner):
            raise RuntimeError(
                "pip is unavailable for the current interpreter; install python3-pip or use --dependency-mode managed-venv"
            )
        install = _run([sys.executable, "-m", "pip", "install", "--user", "-r", str(req)], runner=runner)
        if install.returncode != 0:
            raise RuntimeError(f"user pip install failed without --break-system-packages: {install.stderr.strip()}")
        check = _run([sys.executable, "-m", "pip", "check"], runner=runner)
        if check.returncode != 0:
            raise RuntimeError(f"pip check failed: {check.stderr.strip() or check.stdout.strip()}")
        return dependency_status(repo_root, mode=mode, data_root=data_root, runner=runner).to_dict() | {
            "changed": True,
            "pip_check": check.stdout.strip(),
        }

    if not has_venv_module():
        raise RuntimeError(
            "python venv module is unavailable; install python3-venv on Debian/Ubuntu, python3 on Fedora, or the Python.org installer on macOS"
        )
    if not req.exists():
        raise RuntimeError(f"requirements file not found: {req}")

    venv_path = managed_venv_path(repo_root, data_root)
    if not venv_path.exists():
        create = _run([sys.executable, "-m", "venv", str(venv_path)], runner=runner)
        if create.returncode != 0:
            raise RuntimeError(f"managed venv creation failed: {create.stderr.strip()}")
    python = venv_python(venv_path)
    if not python.exists():
        raise RuntimeError(f"managed venv interpreter was not created: {python}")

    if not pip_available(python, runner=runner):
        raise RuntimeError(f"pip is unavailable in managed venv: {python}")
    install = _run([str(python), "-m", "pip", "install", "-r", str(req)], runner=runner)
    if install.returncode != 0:
        raise RuntimeError(f"managed venv dependency install failed: {install.stderr.strip()}")
    check = _run([str(python), "-m", "pip", "check"], runner=runner)
    if check.returncode != 0:
        raise RuntimeError(f"managed venv pip check failed: {check.stderr.strip() or check.stdout.strip()}")

    return dependency_status(repo_root, mode=mode, data_root=data_root, runner=runner).to_dict() | {
        "changed": True,
        "pip_check": check.stdout.strip(),
    }


def tool_status(name: str) -> dict:
    path = shutil.which(name)
    return {"name": name, "path": path, "ok": path is not None}
