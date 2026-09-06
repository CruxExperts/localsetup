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


def inspect(*, package_root: Path | None = None, home: Path | None = None, runtime_root: Path | None = None, profiles_path: Path | None = None) -> dict:
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
    from . import runtime_diagnostics
    paths = locations(home if home is not None else Path.home())
    if runtime_root is not None:
        paths['runtimes'] = str(runtime_root)
    if profiles_path is not None:
        paths['profiles'] = str(profiles_path)
    runtime = runtime_diagnostics.runtime(Path(paths['runtimes']))
    profiles = runtime_diagnostics.profiles(Path(paths['profiles']))
    if runtime['status'] != 'verified':
        issues.append('Runtime inspection is ' + runtime['status'] + '; inspect setup records and use verified-artifact setup or explicit recovery. Busy upgrades must finish before inspection.')
    if profiles['status'] != 'verified':
        issues.append('Profile configuration is ' + profiles['status'] + '; verify the explicit document, trusted ownership and file/ancestor write permissions. Credentials are not checked.')
    dependencies = runtime.get('dependencies', {'status': 'unavailable'})
    native = runtime.get('native_sandbox', {'status': 'unavailable'})
    if dependencies['status'] != 'verified':
        issues.append('Runtime dependency metadata is ' + dependencies['status'] + '; reinstall from verified artifacts and the matching locked offline dependency set.')
    if native['status'] != 'present_unprobed':
        issues.append('Native sandbox is ' + native['status'] + '; tool-enabled runs require a qualified bundled backend on a supported platform.')
    issues.append('Native execution, resource delegation and credentials remain per-run checks; doctor does not probe or authorize them.')
    ready = dependencies['status'] == 'verified' and state == 'verified' and runtime['status'] == 'verified' and profiles['status'] == 'verified'
    return {
        "schema_version": 1,
        "product": PRODUCT_NAME,
        "application": CLI_NAME,
        "framework_version": framework_version(),
        "status": "static_verified" if ready else "not_ready",
        "runtime": runtime,
        "profiles": profiles,
        "sdk_payload": state,
        "execution_available": False,
        "execution_implemented": True,
        "locations": paths,
        "issues": issues,
    }
