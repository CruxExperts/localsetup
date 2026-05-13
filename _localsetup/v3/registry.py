from __future__ import annotations

from pathlib import Path
from typing import Any

from .lockfile import load_json, save_json


REGISTRY_VERSION = 2


def load_registry(path: Path) -> dict[str, Any]:
    data = load_json(path)
    if not data:
        return {"version": REGISTRY_VERSION, "managed_by": "localsetup-v3", "targets": {}, "packages": {}}
    if int(data.get("version", 1)) < REGISTRY_VERSION:
        return {
            "version": REGISTRY_VERSION,
            "managed_by": data.get("managed_by", "localsetup-v3"),
            "source_commit": data.get("source_commit"),
            "targets": {},
            "packages": {},
            "legacy": data,
        }
    data.setdefault("targets", {})
    data.setdefault("packages", {})
    return data


def package_digest(path: Path) -> str | None:
    marker = path / ".localsetup-managed"
    if not marker.exists():
        return None
    import hashlib

    digest = hashlib.sha256()
    for child in sorted(p for p in path.rglob("*") if p.is_file() and not p.is_symlink()):
        rel = child.relative_to(path).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(child.read_bytes())
    return digest.hexdigest()


def upsert_target(
    registry_path: Path,
    *,
    target_root: Path,
    source_commit: str,
    package_paths: list[Path],
    adapter_targets: list[dict[str, Any]],
) -> dict[str, Any]:
    registry = load_registry(registry_path)
    target_id = str(target_root.resolve(strict=False))
    package_names = [path.name for path in package_paths]
    registry["source_commit"] = source_commit
    registry["canonical_package_root"] = str(package_paths[0].parent) if package_paths else registry.get("canonical_package_root")
    registry["targets"][target_id] = {
        "target_root": str(target_root),
        "source_commit": source_commit,
        "packages": package_names,
        "adapters": adapter_targets,
        "lock_path": str(target_root / ".localsetup" / "lock.json"),
        "registry_path": str(registry_path),
    }
    for path in package_paths:
        package = registry["packages"].setdefault(path.name, {"path": str(path), "refs": [], "digest": None})
        package["path"] = str(path)
        package["digest"] = package_digest(path)
        refs = set(str(ref) for ref in package.get("refs", []))
        refs.add(target_id)
        package["refs"] = sorted(refs)
    save_json(registry_path, registry)
    return registry


def remove_target(registry_path: Path, *, target_root: Path) -> dict[str, Any]:
    registry = load_registry(registry_path)
    target_id = str(target_root.resolve(strict=False))
    registry.get("targets", {}).pop(target_id, None)
    for package_name, package in list(registry.get("packages", {}).items()):
        refs = [ref for ref in package.get("refs", []) if ref != target_id]
        if refs:
            package["refs"] = refs
        else:
            registry["packages"].pop(package_name, None)
    if registry.get("targets") or registry.get("packages"):
        save_json(registry_path, registry)
    elif registry_path.exists():
        registry_path.unlink()
    return registry


def package_has_other_refs(registry: dict[str, Any], package_name: str, *, target_root: Path) -> bool:
    target_id = str(target_root.resolve(strict=False))
    package = registry.get("packages", {}).get(package_name, {})
    return any(ref != target_id for ref in package.get("refs", []))
