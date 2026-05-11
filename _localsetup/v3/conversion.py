from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import shutil

from .aliases import collect_skill_aliases
from .adapters import adapter_path_state, adapter_targets
from .apply import apply_plan
from .dependencies import ensure_dependencies
from .lockfile import save_json
from .manifests import load_pack_config
from .migration import _backup_item, conservative_migrate, detect_legacy_artifacts
from .paths import expand_user_path
from .plan import build_install_plan
from .verify import verify_install


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _default_backup_root(target_root: Path) -> Path:
    return target_root / ".localsetup" / "backups" / f"conversion-{_stamp()}"


def _framework_sync_needed(source_root: Path, target_root: Path) -> bool:
    source_framework = (source_root / "_localsetup").resolve(strict=False)
    target_framework = (target_root / "_localsetup").resolve(strict=False)
    return source_framework != target_framework


def _inventory(
    source_root: Path,
    *,
    home: Path,
    platform_ids: list[str] | None,
    target_root: Path,
) -> list[dict]:
    artifacts = detect_legacy_artifacts(source_root, home=home, platform_ids=platform_ids, target_root=target_root)
    target_framework = target_root / "_localsetup"
    if target_framework.exists() and _framework_sync_needed(source_root, target_root):
        artifacts.append(
            {
                "kind": "legacy_framework_source",
                "path": str(target_framework),
                "managed": False,
                "details": {"replacement": str(source_root / "_localsetup")},
            }
        )
    return artifacts


def _conversion_blockers(
    source_root: Path,
    *,
    home: Path,
    platform_ids: list[str] | None,
    target_root: Path,
    artifacts: list[dict],
) -> list[dict]:
    blockers: list[dict] = []
    pack = load_pack_config(source_root)
    global_root = expand_user_path(pack.global_root, home)
    aliases = collect_skill_aliases(source_root / "_localsetup" / "skills")
    for target in adapter_targets(source_root, home, platform_ids=platform_ids, target_root=target_root):
        state = adapter_path_state(target["repo_path"], global_root)
        if state["collision_reason"]:
            blockers.append(
                {
                    "kind": "adapter_collision",
                    "path": str(target["repo_path"]),
                    "reason": state["collision_reason"],
                    "remediation": f"move or remove {target['repo_path']} before conversion",
                }
            )
    for artifact in artifacts:
        if artifact["kind"] == "legacy_global_skill" and not artifact.get("managed"):
            blockers.append(
                {
                    "kind": "legacy_global_skill",
                    "path": artifact["path"],
                    "reason": "legacy global skill is not marked as Localsetup-managed",
                    "remediation": f"move or review {artifact['path']} before conversion",
                }
            )
        if artifact["kind"] == "legacy_global_skill" and artifact.get("managed"):
            path = Path(artifact["path"])
            if path.name in aliases:
                dest = path.with_name(aliases[path.name])
                if dest.exists() and not (dest / ".localsetup-managed").exists():
                    blockers.append(
                        {
                            "kind": "global_skill_collision",
                            "path": str(dest),
                            "reason": "destination skill exists and is unmanaged",
                            "remediation": f"move or review {dest} before conversion",
                        }
                    )
    return blockers


def _archive_target_artifacts(artifacts: list[dict], backup_root: Path, target_root: Path) -> list[str]:
    backed_up: list[str] = []
    for artifact in artifacts:
        if artifact["kind"] not in {"lockfile", "legacy_framework_source"}:
            continue
        path = Path(artifact["path"])
        if not (path.exists() or path.is_symlink()):
            continue
        backed_up.append(_backup_item(path, backup_root, target_root))
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    return backed_up


def _sync_framework_source(source_root: Path, target_root: Path) -> dict:
    if not _framework_sync_needed(source_root, target_root):
        return {"skipped": True, "reason": "source and target are the same checkout"}
    source = source_root / "_localsetup"
    dest = target_root / "_localsetup"
    pack = load_pack_config(source_root)

    def is_package_runtime_data(rel_parts: list[str]) -> bool:
        return (
            len(rel_parts) >= 5
            and rel_parts[0] == "_localsetup"
            and rel_parts[1] in {"skills", "workflows"}
            and rel_parts[3:5] == ["scripts", "data"]
        )

    def ignore_private(dir_path: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        directory = Path(dir_path)
        for name in names:
            candidate = directory / name
            rel_repo = candidate.relative_to(source_root).as_posix()
            parts = rel_repo.split("/")
            if (
                "__pycache__" in parts
                or ".cache" in parts
                or ".pytest_cache" in parts
                or ".mypy_cache" in parts
                or ".ruff_cache" in parts
                or rel_repo.endswith((".pyc", ".pyo"))
                or is_package_runtime_data(parts)
            ):
                ignored.add(name)
                continue
            for private in pack.private_paths:
                private_name = private.rstrip("/")
                if rel_repo == private_name or rel_repo.startswith(private_name + "/"):
                    ignored.add(name)
                    break
        return ignored

    shutil.copytree(
        source,
        dest,
        symlinks=True,
        ignore=ignore_private,
    )
    return {"skipped": False, "source": str(source), "target": str(dest)}


def convert_repo(
    source_root: Path,
    *,
    home: Path,
    packs: list[str] | None = None,
    platform_ids: list[str] | None = None,
    attach_mode: str = "symlink",
    target_root: Path | None = None,
    backup_dir: Path | None = None,
    dependency_mode: str = "prompt-only",
    apply: bool = False,
) -> dict:
    target = (target_root or source_root).resolve(strict=False)
    backup_root = (backup_dir or _default_backup_root(target)).resolve(strict=False)
    artifacts = _inventory(source_root, home=home, platform_ids=platform_ids, target_root=target)
    blockers = _conversion_blockers(source_root, home=home, platform_ids=platform_ids, target_root=target, artifacts=artifacts)
    payload = {
        "ok": not blockers,
        "applied": False,
        "source_root": str(source_root),
        "target_root": str(target),
        "backup_dir": str(backup_root),
        "artifacts": artifacts,
        "blockers": blockers,
        "backed_up": [],
        "migration": None,
        "framework_sync": None,
        "install": None,
        "verify": None,
    }
    migration_preflight = conservative_migrate(
        source_root,
        home=home,
        platform_ids=platform_ids,
        target_root=target,
        backup_dir=backup_root / "migration",
        apply=False,
    )
    if migration_preflight["blockers"]:
        payload["ok"] = False
        payload["migration"] = migration_preflight
        payload["blockers"].extend(migration_preflight["blockers"])
    if payload["blockers"] or not apply:
        if apply:
            backup_root.mkdir(parents=True, exist_ok=True)
            save_json(backup_root / "conversion-report.json", payload)
        return payload

    backup_root.mkdir(parents=True, exist_ok=True)
    payload["backed_up"].extend(_archive_target_artifacts(artifacts, backup_root, target))
    migration = conservative_migrate(
        source_root,
        home=home,
        platform_ids=platform_ids,
        target_root=target,
        backup_dir=backup_root / "migration",
        apply=True,
    )
    payload["migration"] = migration
    if not migration["ok"]:
        payload["ok"] = False
        save_json(backup_root / "conversion-report.json", payload)
        return payload

    payload["framework_sync"] = _sync_framework_source(source_root, target)
    dependency_info = ensure_dependencies(source_root, mode=dependency_mode) if dependency_mode != "prompt-only" else None
    plan = build_install_plan(
        source_root,
        home=home,
        packs=packs,
        attach_mode=attach_mode,
        platform_ids=platform_ids,
        target_root=target,
    )
    payload["install"] = apply_plan(source_root, plan, home=home, dependency_info=dependency_info, target_root=target)
    if dependency_info:
        payload["install"]["dependencies"] = dependency_info
    payload["verify"] = verify_install(source_root, home=home, platform_ids=platform_ids, target_root=target)
    payload["ok"] = bool(payload["verify"]["ok"])
    payload["applied"] = True
    save_json(backup_root / "conversion-report.json", payload)
    return payload
