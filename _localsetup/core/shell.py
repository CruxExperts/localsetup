from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import stat

from .git_subprocess import run_git


SHIM_NAME = "localsetup"
SHIM_ENV = "LOCALSETUP_GLOBAL_SHIM"
SHIM_MARKER = "managed_by=localsetup"


def user_bin_dir(home: Path) -> Path:
    return home / ".local" / "bin"


def shim_path(home: Path) -> Path:
    return user_bin_dir(home) / SHIM_NAME


def path_status(bin_dir: Path, *, path_env: str | None = None) -> dict:
    raw_path = os.environ.get("PATH", "") if path_env is None else path_env
    entries = [Path(entry).expanduser().resolve(strict=False) for entry in raw_path.split(os.pathsep) if entry]
    resolved = bin_dir.expanduser().resolve(strict=False)
    return {
        "bin_dir": str(resolved),
        "on_path": resolved in entries,
        "path_entries": [str(entry) for entry in entries],
    }


def _managed_shim_content(source_root: Path, home: Path) -> str:
    source = str(source_root.resolve(strict=False))
    home_value = str(home.resolve(strict=False))
    quoted_source = shlex.quote(source)
    quoted_home = shlex.quote(home_value)
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            f"# {SHIM_MARKER}",
            "set -euo pipefail",
            f"LOCALSETUP_SOURCE_ROOT={quoted_source}",
            f"LOCALSETUP_HOME={quoted_home}",
            "export LOCALSETUP_SOURCE_ROOT",
            f"export {SHIM_ENV}=1",
            'LOCALSETUP_TOOL="$LOCALSETUP_SOURCE_ROOT/_localsetup/tools/localsetup.py"',
            'LOCALSETUP_PROJECT_PYTHON="$LOCALSETUP_SOURCE_ROOT/.venv/bin/python"',
            'if [ -x "$LOCALSETUP_PROJECT_PYTHON" ] && "$LOCALSETUP_PROJECT_PYTHON" "$LOCALSETUP_TOOL" --help >/dev/null 2>&1; then',
            '  exec "$LOCALSETUP_PROJECT_PYTHON" "$LOCALSETUP_TOOL" --source-root "$LOCALSETUP_SOURCE_ROOT" --home "$LOCALSETUP_HOME" "$@"',
            "fi",
            'if python3 "$LOCALSETUP_TOOL" --help >/dev/null 2>&1; then',
            '  exec python3 "$LOCALSETUP_TOOL" --source-root "$LOCALSETUP_SOURCE_ROOT" --home "$LOCALSETUP_HOME" "$@"',
            "fi",
            'echo "localsetup: no usable Python runtime for Localsetup." >&2',
            'echo "The source checkout .venv is missing or unhealthy, and system python3 cannot import Localsetup." >&2',
            'printf "Repair: %q --directory %q --sync-env --non-interactive --yes\\n" "$LOCALSETUP_SOURCE_ROOT/install" "$LOCALSETUP_SOURCE_ROOT" >&2',
            "exit 2",
            "",
        ]
    )


def is_managed_shim(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    marker_found = any(line.lstrip("# ").strip() == SHIM_MARKER for line in text.splitlines())
    return marker_found and SHIM_ENV in text


def _recorded_source_root(path: Path) -> str | None:
    if not is_managed_shim(path):
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        if line.startswith("LOCALSETUP_SOURCE_ROOT="):
            value = line.split("=", 1)[1].strip()
            try:
                parts = shlex.split(value)
            except ValueError:
                return value
            return parts[0] if parts else value
    return None


def register_shell_command(source_root: Path, *, home: Path, path_env: str | None = None) -> dict:
    if not (source_root / "_localsetup" / "tools" / "localsetup.py").is_file():
        raise FileNotFoundError(f"missing Localsetup source checkout: {source_root}")

    bin_dir = user_bin_dir(home)
    path = shim_path(home)
    if path.exists() and not is_managed_shim(path):
        raise RuntimeError(f"refusing to overwrite unmanaged localsetup command: {path}")

    bin_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(_managed_shim_content(source_root, home), encoding="utf-8")
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    status = path_status(bin_dir, path_env=path_env)
    found = shutil.which(SHIM_NAME, path=path_env)
    warnings = [] if status["on_path"] else [f"{status['bin_dir']} is not on PATH; add it before using `localsetup` globally"]
    if found and Path(found).resolve(strict=False) != path.resolve(strict=False):
        warnings.append(f"`localsetup` resolves to {found} before the managed shim at {path}")
    return {
        "ok": True,
        "shim": str(path),
        "source_root": str(source_root.resolve(strict=False)),
        "managed": True,
        "path": status,
        "which": found,
        "warnings": warnings,
    }


def shell_registration_status(source_root: Path, *, home: Path, path_env: str | None = None) -> dict:
    path = shim_path(home)
    status = path_status(path.parent, path_env=path_env)
    managed = is_managed_shim(path)
    found = shutil.which(SHIM_NAME, path=path_env)
    recorded_source = _recorded_source_root(path)
    warnings = [] if status["on_path"] else [f"{status['bin_dir']} is not on PATH; add it before using `localsetup` globally"]
    if found and Path(found).resolve(strict=False) != path.resolve(strict=False):
        warnings.append(f"`localsetup` resolves to {found} before the managed shim at {path}")
    return {
        "shim": str(path),
        "exists": path.exists(),
        "managed": managed,
        "source_root": recorded_source if managed else None,
        "expected_source_root": str(source_root.resolve(strict=False)),
        "path": status,
        "which": found,
        "warnings": warnings,
    }


def detect_invocation_target(cwd: Path | None = None) -> Path:
    start = (cwd or Path.cwd()).resolve(strict=False)
    try:
        completed = run_git(
            start,
            ["rev-parse", "--show-toplevel"],
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return start
    if completed.returncode == 0:
        value = completed.stdout.strip()
        if value:
            return Path(value).expanduser().resolve(strict=False)
    return start
