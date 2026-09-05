"""Read-only bootstrap inspection without loading the agent SDK or providers."""
from __future__ import annotations

from pathlib import Path

from ..branding import CLI_NAME, PRODUCT_NAME
from ..framework_version import framework_version
from ..sdk_payload.integrity import verify


def locations(home: Path) -> dict[str, str]:
    """Match the existing global framework home; inspection creates no paths."""
    root = home / ".local" / "share" / "localsetup"
    return {
        "state": str(root / "state" / "lscli"),
        "profiles": str(root / "config" / "lscli" / "profiles.json"),
        "runtimes": str(root / "runtimes" / "lscli"),
    }


def inspect(*, package_root: Path | None = None, home: Path | None = None) -> dict:
    root = package_root if package_root is not None else Path(__file__).resolve().parents[2]
    payload = root / "_sdk_payload"
    state = "missing"
    issues = []
    try:
        if payload.exists() or payload.is_symlink():
            verify(payload)
            state = "verified"
        else:
            issues.append("Installed SDK payload is missing; use a framework wheel containing the private payload.")
    except (OSError, ValueError, TypeError, RecursionError):
        state = "invalid"
        issues.append("SDK payload integrity failed; reinstall from a verified framework artifact.")
    issues.append("Coding runs require an explicit profile, task grant and successful per-run sandbox/resource preflight.")
    return {
        "schema_version": 1,
        "product": PRODUCT_NAME,
        "application": CLI_NAME,
        "framework_version": framework_version(),
        "status": "not_ready",
        "sdk_payload": state,
        "execution_available": False,
        "execution_implemented": True,
        "locations": locations(home if home is not None else Path.home()),
        "issues": issues,
    }
