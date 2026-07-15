"""
Purpose: Shared helper for runtime dependency checks across all framework Python tools.
Created: 2026-02-27
Last Updated: 2026-02-27

Tools call require_deps() at startup. If any listed package is missing the helper
prints an actionable error message to stderr and exits with code 2.

The .deps-missing sentinel file is written only by the install scripts as a
user-visible notice. This module NEVER reads the sentinel; it always performs a
live importlib check so that a stale sentinel from an older install cannot
falsely block tools on a system where the packages are in fact present.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

# Maps import names to the project dependency names declared in pyproject.toml.
_REGISTRY: dict[str, str] = {
    "yaml": "PyYAML",
    "requests": "requests",
    "frontmatter": "python-frontmatter",
    "cryptography": "cryptography",
    "pgpy": "PGPy",
    "jsonschema": "jsonschema",
}

# Path to the sentinel file written by install when deps were absent at install time.
# Tools do NOT read this; it is here only so install scripts can import the path.
SENTINEL = Path(__file__).parents[1] / ".deps-missing"


def _import_fails(import_name: str) -> bool:
    """Return True if the given import name cannot be resolved at runtime."""
    try:
        importlib.import_module(import_name)
        return False
    except ImportError:
        return True


def require_deps(names: list[str]) -> None:
    """Exit with code 2 if any of the listed import names cannot be imported.

    Always performs a live import check. The .deps-missing sentinel file is
    never consulted so a stale sentinel from an older install has no effect.

    Args:
        names: Python import names to check, e.g. ["requests", "frontmatter"].
    """
    missing = [n for n in names if _import_fails(n)]
    if not missing:
        return

    project_deps = ", ".join(_REGISTRY.get(n, n) for n in missing)
    print(
        f"[FATAL] Missing Python packages: {', '.join(missing)}\n"
        f"  Project dependencies: {project_deps}\n"
        f"  Sync with: uv sync --locked --no-dev\n"
        f"  Or re-run the framework install script with --sync-env",
        file=sys.stderr,
    )
    sys.exit(2)


def check_deps(names: list[str]) -> list[str]:
    """Return a list of import names that are currently missing (no exit).

    Useful for install scripts that want to report status without aborting.
    """
    return [n for n in names if _import_fails(n)]
