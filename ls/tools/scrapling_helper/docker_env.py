"""
Purpose: Docker-based execution helpers for Scrapling integration.
Created: 2026-03-16
Last Updated: 2026-03-16
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import ScraplingConfig


@dataclass
class DockerEnvStatus:
    available: bool
    details: str


def detect_docker() -> DockerEnvStatus:
    docker_bin = shutil.which("docker")
    if not docker_bin:
        return DockerEnvStatus(available=False, details="docker executable not found on PATH")

    proc = subprocess.run(
        [docker_bin, "version", "--format", "{{.Server.Version}}"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        return DockerEnvStatus(
            available=False,
            details=f"docker version command failed: {proc.stderr.strip()}",
        )

    return DockerEnvStatus(
        available=True,
        details=f"docker server version {proc.stdout.strip()}",
    )


def build_scrapling_docker_command(
    cfg: ScraplingConfig,
    args: list[str],
    workdir: Optional[Path] = None,
) -> list[str]:
    docker_bin = shutil.which("docker") or "docker"
    workdir = (workdir or Path.cwd()).resolve()

    return [
        docker_bin,
        "run",
        "--rm",
        "-w",
        "/workspace",
        "-v",
        f"{workdir}:/workspace",
        cfg.docker_image,
        *args,
    ]
