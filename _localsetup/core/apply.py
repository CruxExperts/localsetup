from __future__ import annotations

import json
from pathlib import Path
import os
import shutil
import time
import uuid

from .lockfile import save_json
from .locking import package_root_lock
from .manifests import load_pack_config
from .models import DeployPlan
from .paths import ensure_dir, legacy_target_lockfile_path, repo_path, target_lockfile_path
from .adapters import ADAPTER_MARKER_JSON, adapter_path_state, legacy_global_roots, _is_safe_adapter_package_name
from .registry import upsert_target
from .provenance import build_package_marker, is_managed_package, load_package_marker, managed_marker_path, marker_public_snapshot
from .source import source_commit


SAFE_ADAPTER_STATUS_CODES = {
    "absent",
    "managed_scoped_adapter",
    "managed_portable_adapter",
    "legacy_monolithic_symlink",
    "mixed_managed_custom_adapter",
}


def _unsafe_same_name_adapter_entries(action, state: dict) -> list[str]:
    selected = {str(name) for name in action.details.get("packages", [])}
    unsafe = set(state.get("custom_entries", [])) | set(state.get("unknown_entries", []))
    return sorted(selected & unsafe)


def _journal_root(attachment_root: Path) -> Path:
    return attachment_root / ".localsetup" / "install-journal"


def _journal_path(attachment_root: Path, txid: str) -> Path:
    return _journal_root(attachment_root) / f"{int(time.time() * 1000)}-{txid}.json"


def _staging_root(global_root: Path, txid: str) -> Path:
    return global_root / ".localsetup-staging" / txid


def _same_filesystem_replace(src: Path, dest: Path) -> None:
    os.replace(src, dest)


def _write_journal(path: Path, payload: dict) -> None:
    save_json(path, payload)


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _cleanup_staging(journal: dict) -> None:
    staging_roots = {
        Path(item["staging_root"])
        for item in journal.get("touched", [])
        if isinstance(item, dict) and item.get("kind") == "staging_root" and item.get("staging_root")
    }
    for root in staging_roots:
        if root.exists() or root.is_symlink():
            _remove_path(root)


def _cleanup_backups(journal: dict) -> None:
    for item in journal.get("touched", []):
        if not isinstance(item, dict) or item.get("kind") not in {"managed_package", "adapter", "file_state"}:
            continue
        backup = item.get("backup")
        if backup:
            backup_path = Path(backup)
            if backup_path.exists() or backup_path.is_symlink():
                _remove_path(backup_path)


def _restore_failed_mutations(journal: dict) -> None:
    for item in reversed(journal.get("touched", [])):
        if not isinstance(item, dict) or item.get("kind") not in {"managed_package", "adapter", "file_state", "legacy_lockfile"}:
            continue
        path = Path(str(item["path"]))
        backup = Path(str(item["backup"])) if item.get("backup") else None
        existed = bool(item.get("existed"))
        if path.exists() or path.is_symlink():
            _remove_path(path)
        if existed and backup and (backup.exists() or backup.is_symlink()):
            _same_filesystem_replace(backup, path)
        elif backup and (backup.exists() or backup.is_symlink()):
            _remove_path(backup)


def _record_file_state(journal: dict, journal_path: Path, path: Path) -> None:
    if any(item.get("kind") == "file_state" and item.get("path") == str(path) for item in journal.get("touched", []) if isinstance(item, dict)):
        return
    backup = path.with_name(f".{path.name}.localsetup-backup-{uuid.uuid4().hex}")
    existed = path.exists() or path.is_symlink()
    if existed:
        if path.is_symlink():
            _same_filesystem_replace(path, backup)
            _same_filesystem_replace(backup, path)
        else:
            shutil.copy2(path, backup)
    journal.setdefault("touched", []).append(
        {"kind": "file_state", "path": str(path), "backup": str(backup), "existed": existed}
    )
    _write_journal(journal_path, journal)


def _archive_legacy_lockfile(legacy_lockfile: Path, attachment_root: Path, txid: str) -> str | None:
    if not (legacy_lockfile.exists() or legacy_lockfile.is_symlink()):
        return None
    backup = attachment_root / ".localsetup" / "backups" / f"legacy-lock-{txid}" / legacy_lockfile.name
    backup.parent.mkdir(parents=True, exist_ok=True)
    if legacy_lockfile.is_symlink():
        backup.write_text(f"symlink -> {legacy_lockfile.readlink()}\n", encoding="utf-8")
        legacy_lockfile.unlink()
    else:
        shutil.copy2(legacy_lockfile, backup)
        legacy_lockfile.unlink()
    return str(backup)


def _install_managed_packages(
    repo_root: Path,
    global_root: Path,
    package_names: list[str],
    source_subdir: str,
    *,
    staging_root: Path | None = None,
    journal: dict | None = None,
    journal_path: Path | None = None,
) -> list[str]:
    ensure_dir(global_root)
    installed: list[str] = []
    source_root = repo_root / "_localsetup" / source_subdir

    for package_name in sorted(package_names):
        src = source_root / package_name
        dest = global_root / package_name
        staged = (staging_root / source_subdir / package_name) if staging_root else dest
        if dest.exists() and not is_managed_package(dest):
            raise RuntimeError(f"refusing to overwrite unmanaged package path: {dest}")
        package_type = "workflow" if source_subdir == "workflows" else "skill"
        if staging_root:
            if journal is not None and not any(
                item.get("kind") == "staging_root" and item.get("staging_root") == str(staging_root)
                for item in journal.get("touched", [])
                if isinstance(item, dict)
            ):
                journal.setdefault("touched", []).append({"kind": "staging_root", "staging_root": str(staging_root)})
                if journal_path:
                    _write_journal(journal_path, journal)
            if staged.exists():
                shutil.rmtree(staged)
            staged.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, staged)
            save_json(
                managed_marker_path(staged),
                build_package_marker(
                    repo_root,
                    staged,
                    package_name=package_name,
                    package_type=package_type,
                    source_path=src,
                    emitter="package-install",
                    artifact_path=dest,
                ),
            )
            backup = dest.with_name(f".{dest.name}.localsetup-backup-{uuid.uuid4().hex}")
            existed = dest.exists() or dest.is_symlink()
            if journal is not None:
                journal.setdefault("touched", []).append(
                    {
                        "kind": "managed_package",
                        "path": str(dest),
                        "staged": str(staged),
                        "backup": str(backup),
                        "existed": existed,
                    }
                )
                if journal_path:
                    _write_journal(journal_path, journal)
            if existed:
                _same_filesystem_replace(dest, backup)
            _same_filesystem_replace(staged, dest)
        else:
            if dest.exists() or dest.is_symlink():
                _remove_path(dest)
            shutil.copytree(src, dest)
            save_json(
                managed_marker_path(dest),
                build_package_marker(
                    repo_root,
                    dest,
                    package_name=package_name,
                    package_type=package_type,
                    source_path=src,
                    emitter="package-install",
                ),
            )
        installed.append(str(dest))

    return installed


def _install_managed_skills(repo_root: Path, global_root: Path, skill_names: list[str]) -> list[str]:
    return _install_managed_packages(repo_root, global_root, skill_names, "skills")


def _install_managed_workflows(repo_root: Path, global_root: Path, workflow_names: list[str]) -> list[str]:
    return _install_managed_packages(repo_root, global_root, workflow_names, "workflows")


def _codex_agent_source(repo_root: Path, agent_name: str) -> Path:
    return repo_root / "_localsetup" / "adapters" / "codex" / "agents" / f"{agent_name}.toml"


def _install_codex_agents(repo_root: Path, agents_root: Path, agent_names: list[str]) -> list[str]:
    ensure_dir(agents_root)
    installed: list[str] = []
    for agent_name in sorted(set(str(name) for name in agent_names)):
        src = _codex_agent_source(repo_root, agent_name)
        dest = agents_root / f"{agent_name}.toml"
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        installed.append(str(dest))
    return installed


def _prune_unreferenced_managed_packages(
    global_root: Path,
    registry: dict,
    *,
    journal: dict,
    journal_path: Path,
) -> list[str]:
    if not global_root.exists():
        return []
    referenced = {
        name
        for name, package in registry.get("packages", {}).items()
        if isinstance(package, dict) and package.get("refs")
    }
    removed: list[str] = []
    for path in sorted(global_root.iterdir(), key=lambda item: item.name):
        if path.name.startswith(".localsetup-") or path.name in referenced:
            continue
        if not is_managed_package(path):
            continue
        backup = path.with_name(f".{path.name}.localsetup-backup-{uuid.uuid4().hex}")
        journal.setdefault("touched", []).append(
            {"kind": "managed_package", "path": str(path), "backup": str(backup), "existed": True}
        )
        _write_journal(journal_path, journal)
        _same_filesystem_replace(path, backup)
        removed.append(str(path))
    return removed


def _write_scoped_adapter(adapter_path: Path, global_root: Path, package_names: list[str], *, mode: str) -> None:
    ensure_dir(adapter_path)
    portable_marker = adapter_path / ".localsetup-portable"
    if mode != "portable" and portable_marker.exists():
        portable_marker.unlink()
    selected = set(package_names)
    old_marker = adapter_path / ADAPTER_MARKER_JSON
    old_packages: set[str] = set()
    if old_marker.is_file():
        try:
            old_payload = json.loads(old_marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            old_payload = {}
        old_raw = old_payload.get("packages") if isinstance(old_payload, dict) else None
        if isinstance(old_raw, list):
            old_packages = {str(item) for item in old_raw if _is_safe_adapter_package_name(str(item))}
    for stale_package in sorted(old_packages - selected):
        stale_path = adapter_path / stale_package
        if _is_current_managed_adapter_entry(stale_path, global_root, mode):
            _remove_path(stale_path)
    save_json(
        adapter_path / ADAPTER_MARKER_JSON,
        {
            "version": 1,
            "managed_by": "localsetup",
            "mode": mode,
            "global_root": str(global_root),
            "packages": sorted(set(package_names)),
        },
    )
    for package_name in sorted(set(package_names)):
        source = global_root / package_name
        if not source.is_dir():
            raise RuntimeError(f"selected package is missing from managed library: {source}")
        target = adapter_path / package_name
        if target.exists() or target.is_symlink():
            _remove_path(target)
        if mode == "portable":
            shutil.copytree(source, target)
        else:
            target.symlink_to(source, target_is_directory=True)
    if mode == "portable":
        (adapter_path / ".localsetup-portable").write_text("managed_by=localsetup\n", encoding="utf-8")


def _is_current_managed_adapter_entry(path: Path, global_root: Path, mode: str) -> bool:
    if mode == "portable":
        return path.is_dir() and not path.is_symlink() and is_managed_package(path)
    if not path.is_symlink():
        return False
    link_target = path.readlink()
    if not link_target.is_absolute():
        link_target = path.parent / link_target
    return link_target.resolve(strict=False) == (global_root / path.name).resolve(strict=False)


def apply_plan(
    repo_root: Path,
    plan: DeployPlan,
    home: Path,
    dry_run: bool = False,
    dependency_info: dict | None = None,
    target_root: Path | None = None,
) -> dict:
    if dry_run:
        return _apply_plan_unlocked(repo_root, plan, home, dry_run=True, dependency_info=dependency_info, target_root=target_root)
    with package_root_lock(home / ".local" / "share" / "localsetup") as lock:
        result = _apply_plan_unlocked(
            repo_root,
            plan,
            home,
            dry_run=False,
            dependency_info=dependency_info,
            target_root=target_root,
        )
        result["package_root_lock"] = lock
        return result


def preflight_install_plan(repo_root: Path, plan: DeployPlan, home: Path) -> dict:
    blockers: list[dict] = []
    for action in plan.actions:
        if action.kind in {"install_skills", "install_workflows"}:
            source_subdir = "skills" if action.kind == "install_skills" else "workflows"
            names = action.details.get("skills", action.details.get("workflows", []))
            for name in names:
                src = repo_root / "_localsetup" / source_subdir / str(name)
                dest = action.path / str(name)
                if not src.is_dir():
                    blockers.append({"path": str(src), "status_code": "missing_source_package", "reason": "selected package source is missing"})
                elif dest.exists() and not is_managed_package(dest):
                    blockers.append({"path": str(dest), "status_code": "unmanaged_package_path", "reason": "refusing to overwrite unmanaged package path"})
        elif action.kind == "install_codex_agents":
            for name in action.details.get("agents", []):
                src = _codex_agent_source(repo_root, str(name))
                dest = action.path / f"{name}.toml"
                if not src.is_file():
                    blockers.append({"path": str(src), "status_code": "missing_source_agent", "reason": "selected Codex agent source is missing"})
                    continue
                if dest.is_symlink() or (dest.exists() and not dest.is_file()):
                    blockers.append(
                        {
                            "path": str(dest),
                            "status_code": "codex_agent_conflict",
                            "reason": "refusing to overwrite existing Codex agent path that is not a regular file",
                        }
                    )
                    continue
                if dest.is_file():
                    try:
                        existing = dest.read_text(encoding="utf-8")
                    except (OSError, UnicodeDecodeError) as exc:
                        blockers.append(
                            {
                                "path": str(dest),
                                "status_code": "codex_agent_conflict",
                                "reason": f"refusing to overwrite unreadable existing Codex agent file: {exc}",
                            }
                        )
                        continue
                    if existing == src.read_text(encoding="utf-8"):
                        continue
                    blockers.append(
                        {
                            "path": str(dest),
                            "status_code": "codex_agent_conflict",
                            "reason": "refusing to overwrite existing Codex agent file with different content",
                        }
                    )
        elif action.kind == "attach_repo_path":
            global_root = Path(action.details["global_root"])
            state = adapter_path_state(action.path, global_root, known_global_roots=legacy_global_roots(home))
            if state["status_code"] not in SAFE_ADAPTER_STATUS_CODES:
                blockers.append(
                    {
                        "path": str(action.path),
                        "status_code": state["status_code"],
                        "reason": state["collision_reason"] or "adapter target is not safe to mutate",
                    }
                )
                continue
            unsafe_entries = _unsafe_same_name_adapter_entries(action, state)
            if unsafe_entries:
                blockers.append(
                    {
                        "path": str(action.path),
                        "status_code": "adapter_custom_package_name_collision",
                        "reason": "adapter contains custom or unknown entries with selected Localsetup package names",
                        "entries": unsafe_entries,
                    }
                )
    return {"ok": not blockers, "blockers": blockers}


def _apply_plan_unlocked(
    repo_root: Path,
    plan: DeployPlan,
    home: Path,
    dry_run: bool = False,
    dependency_info: dict | None = None,
    target_root: Path | None = None,
) -> dict:
    executed: list[str] = []
    installed_skills: list[str] = []
    installed_workflows: list[str] = []
    installed_codex_agents: list[str] = []
    metadata_target_root = plan.rollback_metadata.get("target_root")
    metadata_attachment_root = Path(metadata_target_root) if metadata_target_root else None
    if target_root is not None and metadata_attachment_root is not None:
        if target_root.resolve(strict=False) != metadata_attachment_root.resolve(strict=False):
            raise ValueError("target_root does not match install plan target_root")
    attachment_root = target_root or metadata_attachment_root or repo_root
    preflight = preflight_install_plan(repo_root, plan, home)
    if not preflight["ok"]:
        raise RuntimeError(f"install preflight failed: {preflight['blockers']}")
    txid = uuid.uuid4().hex
    journal_path = _journal_path(attachment_root, txid)
    journal = {
        "version": 1,
        "txid": txid,
        "status": "started",
        "started_at_unix": int(time.time()),
        "source_commit": source_commit(repo_root),
        "target_root": str(attachment_root),
        "touched": [],
    }
    if not dry_run:
        ensure_dir(journal_path.parent)
        _write_journal(journal_path, journal)
    try:
        for action in plan.actions:
            if action.kind == "ensure_dir":
                if not dry_run:
                    ensure_dir(action.path)
                executed.append(f"ensure_dir:{action.path}")
            elif action.kind == "write_registry":
                if not dry_run:
                    ensure_dir(action.path.parent)
                    journal["touched"].append({"kind": "registry", "path": str(action.path)})
                    _write_journal(journal_path, journal)
                executed.append(f"write_registry:{action.path}")
            elif action.kind == "install_skills":
                if not dry_run:
                    installed_skills = _install_managed_packages(
                        repo_root,
                        action.path,
                        action.details["skills"],
                        "skills",
                        staging_root=_staging_root(action.path, txid),
                        journal=journal,
                        journal_path=journal_path,
                    )
                executed.append(f"install_skills:{action.path}")
            elif action.kind == "install_workflows":
                if not dry_run:
                    installed_workflows = _install_managed_packages(
                        repo_root,
                        action.path,
                        action.details["workflows"],
                        "workflows",
                        staging_root=_staging_root(action.path, txid),
                        journal=journal,
                        journal_path=journal_path,
                    )
                executed.append(f"install_workflows:{action.path}")
            elif action.kind == "install_codex_agents":
                if not dry_run:
                    ensure_dir(action.path)
                    for name in action.details.get("agents", []):
                        _record_file_state(journal, journal_path, action.path / f"{name}.toml")
                    installed_codex_agents = _install_codex_agents(repo_root, action.path, action.details["agents"])
                executed.append(f"install_codex_agents:{action.path}")
            elif action.kind == "attach_repo_path":
                if not dry_run:
                    ensure_dir(action.path.parent)
                    mode = action.details.get("mode", "symlink")
                    global_root = Path(action.details["global_root"])
                    package_names = [str(name) for name in action.details.get("packages", [])]
                    state = adapter_path_state(action.path, global_root, known_global_roots=legacy_global_roots(home))
                    backup = action.path.with_name(f".{action.path.name}.localsetup-backup-{uuid.uuid4().hex}")
                    existed = action.path.exists() or action.path.is_symlink()
                    in_place = state["status_code"] in {
                        "managed_scoped_adapter",
                        "managed_portable_adapter",
                        "mixed_managed_custom_adapter",
                    }
                    journal["touched"].append(
                        {
                            "kind": "adapter",
                            "path": str(action.path),
                            "backup": str(backup),
                            "existed": existed,
                        }
                    )
                    _write_journal(journal_path, journal)
                    if action.path.exists() or action.path.is_symlink():
                        if in_place:
                            shutil.copytree(action.path, backup, symlinks=True)
                        elif state["collision_reason"]:
                            raise RuntimeError(f"refusing to replace {state['collision_reason']} at adapter path: {action.path}")
                        else:
                            _same_filesystem_replace(action.path, backup)
                    _write_scoped_adapter(action.path, global_root, package_names, mode=mode)
                executed.append(f"attach_repo_path:{action.path}")
    except Exception as exc:
        if not dry_run:
            journal["status"] = "failed"
            journal["failed_at_unix"] = int(time.time())
            journal["error"] = str(exc)
            _cleanup_staging(journal)
            _restore_failed_mutations(journal)
            _write_journal(journal_path, journal)
        raise

    pack = load_pack_config(repo_root)
    lockfile_path = repo_path(attachment_root, pack.lockfile, "repo.lockfile")
    if lockfile_path.name != "lock.json" or lockfile_path.parent.name != ".localsetup":
        lockfile_path = target_lockfile_path(attachment_root)
    adapter_actions = [a for a in plan.actions if a.kind == "attach_repo_path"]
    lock_payload = {
        "version": 2,
        "pack": pack.pack_id,
        "namespace": pack.namespace,
        "source_commit": source_commit(repo_root),
        "source_root": str(repo_root),
        "localsetup_home": str(home / ".local" / "share" / "localsetup"),
        "target_root": str(attachment_root),
        "aliases": plan.rollback_metadata.get("aliases", {}),
        "skills": plan.rollback_metadata.get("skills", []),
        "workflows": plan.rollback_metadata.get("workflows", []),
        "codex_agents": plan.rollback_metadata.get("codex_agents", []),
        "global_baseline_selectors": plan.rollback_metadata.get("global_baseline_selectors", {}),
        "global_baseline_packs": plan.rollback_metadata.get("global_baseline_packs", []),
        "global_baseline_skills": plan.rollback_metadata.get("global_baseline_skills", []),
        "global_baseline_workflows": plan.rollback_metadata.get("global_baseline_workflows", []),
        "global_baseline_packages": plan.rollback_metadata.get("global_baseline_packages", []),
        "repo_selectors": plan.rollback_metadata.get("repo_selectors", {}),
        "repo_packs": plan.rollback_metadata.get("repo_packs", []),
        "repo_skills": plan.rollback_metadata.get("repo_skills", []),
        "repo_workflows": plan.rollback_metadata.get("repo_workflows", []),
        "repo_packages": plan.rollback_metadata.get("repo_packages", []),
        "adapter_state": [s for s in plan.rollback_metadata.get("repo_links", [])],
        "adapter_targets": [
            {
                "platform": action.details.get("platform"),
                "path": str(action.path),
                "mode": action.details.get("mode", "symlink"),
                "global_root": action.details.get("global_root"),
                "packages": action.details.get("packages", []),
            }
            for action in adapter_actions
        ],
        "platforms": plan.rollback_metadata.get("platforms", []),
        "global_only": plan.rollback_metadata.get("global_only", False),
        "attach_mode": plan.rollback_metadata.get("attach_mode", "symlink"),
        "installed_skills": installed_skills,
        "installed_workflows": installed_workflows,
        "installed_codex_agents": installed_codex_agents,
        "adapter_packages": plan.rollback_metadata.get("adapter_packages", []),
        "dependency_mode": (dependency_info or {}).get("mode"),
        "python_interpreter": (dependency_info or {}).get("interpreter"),
        "dependency_state": (dependency_info or {}).get("lock"),
    }
    registry_actions = [a for a in plan.actions if a.kind == "write_registry"]
    if registry_actions:
        lock_payload["registry_path"] = str(registry_actions[0].path)
    global_roots = [a.path for a in plan.actions if a.kind in {"install_skills", "install_workflows"}]
    if global_roots:
        lock_payload["package_root"] = str(global_roots[0])
    lock_payload["package_provenance"] = {
        Path(path).name: marker_public_snapshot(load_package_marker(Path(path)))
        for path in [*installed_skills, *installed_workflows]
    }
    legacy_lockfile = legacy_target_lockfile_path(attachment_root)
    if legacy_lockfile.exists() and legacy_lockfile != lockfile_path:
        lock_payload["migration_origin"] = {"legacy_lockfile": str(legacy_lockfile)}
    if not dry_run:
        try:
            if registry_actions:
                _record_file_state(journal, journal_path, registry_actions[0].path)
                registry_payload = upsert_target(
                    registry_actions[0].path,
                    target_root=attachment_root,
                    source_commit=source_commit(repo_root),
                    package_paths=[Path(path) for path in [*installed_skills, *installed_workflows]],
                    adapter_targets=lock_payload["adapter_targets"],
                    global_baseline={
                        "selectors": lock_payload["global_baseline_selectors"],
                        "packs": lock_payload["global_baseline_packs"],
                        "skills": lock_payload["global_baseline_skills"],
                        "workflows": lock_payload["global_baseline_workflows"],
                        "packages": lock_payload["global_baseline_packages"],
                    },
                    repo_selection={
                        "selectors": lock_payload["repo_selectors"],
                        "packs": lock_payload["repo_packs"],
                        "skills": lock_payload["repo_skills"],
                        "workflows": lock_payload["repo_workflows"],
                        "packages": lock_payload["repo_packages"],
                    },
                )
                if global_roots:
                    pruned = _prune_unreferenced_managed_packages(
                        global_roots[0],
                        registry_payload,
                        journal=journal,
                        journal_path=journal_path,
                    )
                    if pruned:
                        lock_payload["pruned_packages"] = pruned
            _record_file_state(journal, journal_path, lockfile_path)
            legacy_backup = None
            if legacy_lockfile.exists() and legacy_lockfile != lockfile_path:
                legacy_backup = _archive_legacy_lockfile(legacy_lockfile, attachment_root, txid)
                journal["touched"].append(
                    {
                        "kind": "legacy_lockfile",
                        "path": str(legacy_lockfile),
                        "backup": legacy_backup,
                        "existed": True,
                    }
                )
                lock_payload["migration_origin"]["backup"] = legacy_backup
            journal["touched"].append({"kind": "lockfile", "path": str(lockfile_path)})
            _write_journal(journal_path, journal)
            save_json(lockfile_path, lock_payload)
            journal["status"] = "committed"
            journal["committed_at_unix"] = int(time.time())
            _cleanup_staging(journal)
            _cleanup_backups(journal)
            _write_journal(journal_path, journal)
        except Exception as exc:
            journal["status"] = "failed"
            journal["failed_at_unix"] = int(time.time())
            journal["error"] = str(exc)
            _cleanup_staging(journal)
            _restore_failed_mutations(journal)
            _write_journal(journal_path, journal)
            raise
    return {
        "executed": executed,
        "lockfile": str(lockfile_path),
        "dry_run": dry_run,
        "transaction": txid if not dry_run else None,
        "journal": str(journal_path) if not dry_run else None,
        "preflight": preflight,
        "installed_codex_agents": installed_codex_agents,
    }
