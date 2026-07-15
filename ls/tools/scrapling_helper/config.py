"""
Purpose: Central configuration and data paths for Scrapling integration.
Created: 2026-03-16
Last Updated: 2026-03-16
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ScraplingConfig:
    framework_root: Path
    cache_dir: Path
    logs_dir: Path
    outputs_root: Path
    pipx_binary: str
    docker_image: str


def _detect_framework_root() -> Path:
    here = Path(__file__).resolve()
    # ls/tools/scrapling_helper/config.py -> repository root
    return here.parents[3]


def load_config() -> ScraplingConfig:
    framework_root = _detect_framework_root()
    cache_dir = framework_root / ".cache" / "scrapling"
    logs_dir = framework_root / "logs" / "scrapling"
    outputs_root = Path.cwd() / "scrapling_output"

    cache_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    outputs_root.mkdir(parents=True, exist_ok=True)

    pipx_binary = os.environ.get("SCRAPLING_PIPX_BIN", "pipx")
    docker_image = os.environ.get("SCRAPLING_DOCKER_IMAGE", "pyd4vinci/scrapling:latest")

    return ScraplingConfig(
        framework_root=framework_root,
        cache_dir=cache_dir,
        logs_dir=logs_dir,
        outputs_root=outputs_root,
        pipx_binary=pipx_binary,
        docker_image=docker_image,
    )
