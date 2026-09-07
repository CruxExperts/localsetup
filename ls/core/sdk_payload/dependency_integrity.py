"""Standard-library build checks for generated external dependency locks."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tomllib

LOCKS = ("sdk-runtime.lock", "sdk-build.lock")
RECEIPT = "sdk-dependency-receipt.json"


def regular_bytes(path: Path) -> bytes:
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError(f"Dependency input must be a regular file: {path.name}")
    return path.read_bytes()


def source_digest(root: Path) -> str:
    project = tomllib.loads(regular_bytes(root / "pyproject.toml").decode())
    lock = tomllib.loads(regular_bytes(root / "uv.lock").decode())
    # Release-only version updates must not change an external dependency graph.
    project["project"].pop("version", None)
    for package in lock["package"]:
        if package.get("source") == {"editable": "."}:
            package.pop("version", None)
    encoded = json.dumps([project, lock], sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def receipt(root: Path, exports: dict[str, bytes]) -> bytes:
    if set(exports) != set(LOCKS):
        raise ValueError("Dependency export inventory mismatch")
    data = {
        "schema_version": 1,
        "source_sha256": source_digest(root),
        "files": {name: hashlib.sha256(exports[name]).hexdigest() for name in LOCKS},
    }
    return (json.dumps(data, sort_keys=True, indent=2) + "\n").encode()


def verify(root: Path) -> None:
    directory = root / "ls" / "config"
    exports = {name: regular_bytes(directory / name) for name in LOCKS}
    if regular_bytes(directory / RECEIPT) != receipt(root, exports):
        raise ValueError("Stale dependency locks: run generate_sdk_dependency_locks.py")
