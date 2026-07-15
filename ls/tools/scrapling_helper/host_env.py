"""
Purpose: Host-side Scrapling environment detection and pipx/venv management.
Created: 2026-03-16
Last Updated: 2026-03-16
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .config import ScraplingConfig

try:
    from ..cli_helpers import augment_path_for_pipx_apps, pipx_app_bin_dir
except ImportError:  # pragma: no cover - package-local pytest collection path
    from ls.tools.cli_helpers import augment_path_for_pipx_apps, pipx_app_bin_dir


@dataclass
class HostEnvStatus:
    env_type: str  # "pipx-user", "pipx-root", "venv", "system", "missing"
    scrapling_available: bool
    version: Optional[str]
    details: str


def _run_command(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def detect_host_env(cfg: ScraplingConfig) -> HostEnvStatus:
    """
    Detect Scrapling availability on the host using a user-first strategy.

    We prefer user-level pipx installs when present, but also report when the only
    visible binary comes from a system or root-level context.
    """
    # Ensure user-level pipx apps are discoverable before resolving Scrapling.
    augment_path_for_pipx_apps()

    scrapling_path = shutil.which("scrapling")
    if not scrapling_path:
        return HostEnvStatus(
            env_type="missing",
            scrapling_available=False,
            version=None,
            details="scrapling executable not found on PATH",
        )

    # Best-effort classification of the environment based on where the binary lives.
    scrapling_path_obj = Path(scrapling_path)
    home_bin = pipx_app_bin_dir()
    if scrapling_path_obj.is_file() and home_bin in scrapling_path_obj.parents:
        env_type = "pipx-user"
    elif str(scrapling_path_obj).startswith("/root/.local/bin"):
        env_type = "pipx-root"
    else:
        # Fallback classification when we cannot confidently identify pipx usage.
        env_type = "system"

    return HostEnvStatus(
        env_type=env_type,
        scrapling_available=True,
        version=None,
        details=f"scrapling at {scrapling_path}",
    )


def propose_pipx_install(cfg: ScraplingConfig) -> list[str]:
    """
    Propose a user-level pipx install for Scrapling with all extras enabled.

    The caller is responsible for deciding whether to run this plan directly or
    surface it in a sudo-capable tmux session when required.
    """
    return [cfg.pipx_binary, "install", "scrapling[all]"]


def propose_pipx_upgrade(cfg: ScraplingConfig) -> list[str]:
    """
    Propose a user-level pipx upgrade for Scrapling.
    """
    return [cfg.pipx_binary, "upgrade", "scrapling"]


def propose_pipx_bootstrap(userland: bool = True) -> List[List[str]]:
    """
    Propose one or more commands to install pipx itself on Ubuntu-like systems.

    The caller is responsible for choosing which plan to surface or execute.
    When userland is True, only user-scoped commands are returned.
    """
    plans: List[List[str]] = []
    if userland:
        # Pure userland bootstrap without mutating the system Python.
        plans.append(
            [
                "uv",
                "tool",
                "install",
                "pipx",
            ]
        )
        plans.append(
            [
                "pipx",
                "ensurepath",
            ]
        )
    else:
        # Sudo-capable bootstrap for typical Ubuntu servers.
        plans.append(
            [
                "sudo",
                "apt",
                "update",
            ]
        )
        plans.append(
            [
                "sudo",
                "apt",
                "install",
                "-y",
                "pipx",
            ]
        )
        plans.append(
            [
                "pipx",
                "ensurepath",
            ]
        )
    return plans


def apply_command_plan(plan: list[str]) -> dict:
    proc = _run_command(plan)
    return {
        "command": " ".join(plan),
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def status_as_json(status: HostEnvStatus) -> str:
    return json.dumps(
        {
            "env_type": status.env_type,
            "scrapling_available": status.scrapling_available,
            "version": status.version,
            "details": status.details,
        }
    )
