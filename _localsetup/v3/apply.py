from __future__ import annotations

from pathlib import Path
import os
import shutil
import time
import uuid

from .lockfile import save_json
from .manifests import load_pack_config
from .models import DeployPlan
from .paths import ensure_dir, repo_path
from .adapters import adapter_path_state
from .registry import upsert_target
from .source import source_commit


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
        if not isinstance(item, dict) or item.get("kind") not in {"managed_package", "adapter", "file_state"}:
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
        if dest.exists() and not (dest / ".localsetup-managed").exists():
            raise RuntimeError(f"refusing to overwrite unmanaged package path: {dest}")
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
            (staged / ".localsetup-managed").write_text(f"source={source_subdir}/{package_name}\n", encoding="utf-8")
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
            (dest / ".localsetup-managed").write_text(f"source={source_subdir}/{package_name}\n", encoding="utf-8")
        installed.append(str(dest))

    return installed


def _install_managed_skills(repo_root: Path, global_root: Path, skill_names: list[str]) -> list[str]:
    return _install_managed_packages(repo_root, global_root, skill_names, "skills")


def _install_managed_workflows(repo_root: Path, global_root: Path, workflow_names: list[str]) -> list[str]:
    return _install_managed_packages(repo_root, global_root, workflow_names, "workflows")


def apply_plan(
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
    metadata_target_root = plan.rollback_metadata.get("target_root")
    metadata_attachment_root = Path(metadata_target_root) if metadata_target_root else None
    if target_root is not None and metadata_attachment_root is not None:
        if target_root.resolve(strict=False) != metadata_attachment_root.resolve(strict=False):
            raise ValueError("target_root does not match install plan target_root")
    attachment_root = target_root or metadata_attachment_root or repo_root
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
            elif action.kind == "attach_repo_path":
                if not dry_run:
                    ensure_dir(action.path.parent)
                    mode = action.details.get("mode", "symlink")
                    global_root = Path(action.details["global_root"])
                    state = adapter_path_state(action.path, global_root)
                    if (
                        (action.path.exists() or action.path.is_symlink())
                        and not state["collision_reason"]
                        and action.path.is_symlink()
                        and mode == "symlink"
                    ):
                        executed.append(f"attach_repo_path:{action.path}")
                        continue
                    backup = action.path.with_name(f".{action.path.name}.localsetup-backup-{uuid.uuid4().hex}")
                    existed = action.path.exists() or action.path.is_symlink()
                    journal["touched"].append(
                        {"kind": "adapter", "path": str(action.path), "backup": str(backup), "existed": existed}
                    )
                    _write_journal(journal_path, journal)
                    if action.path.exists() or action.path.is_symlink():
                        if state["collision_reason"]:
                            raise RuntimeError(f"refusing to replace {state['collision_reason']} at adapter path: {action.path}")
                        _same_filesystem_replace(action.path, backup)
                    if mode == "portable":
                        shutil.copytree(global_root, action.path)
                        (action.path / ".localsetup-portable").write_text("managed_by=localsetup-v3\n", encoding="utf-8")
                    else:
                        action.path.symlink_to(global_root)
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
    adapter_actions = [a for a in plan.actions if a.kind == "attach_repo_path"]
    lock_payload = {
        "version": 1,
        "pack": pack.pack_id,
        "namespace": pack.namespace,
        "source_commit": source_commit(repo_root),
        "source_root": str(repo_root),
        "target_root": str(attachment_root),
        "aliases": plan.rollback_metadata.get("aliases", {}),
        "skills": plan.rollback_metadata.get("skills", []),
        "workflows": plan.rollback_metadata.get("workflows", []),
        "adapter_state": [s for s in plan.rollback_metadata.get("repo_links", [])],
        "adapter_targets": [
            {
                "platform": action.details.get("platform"),
                "path": str(action.path),
                "mode": action.details.get("mode", "symlink"),
                "global_root": action.details.get("global_root"),
            }
            for action in adapter_actions
        ],
        "platforms": plan.rollback_metadata.get("platforms", []),
        "global_only": plan.rollback_metadata.get("global_only", False),
        "attach_mode": plan.rollback_metadata.get("attach_mode", "symlink"),
        "installed_skills": installed_skills,
        "installed_workflows": installed_workflows,
        "dependency_mode": (dependency_info or {}).get("mode"),
        "python_interpreter": (dependency_info or {}).get("interpreter"),
        "dependency_state": (dependency_info or {}).get("lock"),
    }
    if not dry_run:
        try:
            registry_actions = [a for a in plan.actions if a.kind == "write_registry"]
            if registry_actions:
                _record_file_state(journal, journal_path, registry_actions[0].path)
                upsert_target(
                    registry_actions[0].path,
                    target_root=attachment_root,
                    source_commit=source_commit(repo_root),
                    package_paths=[Path(path) for path in [*installed_skills, *installed_workflows]],
                    adapter_targets=lock_payload["adapter_targets"],
                )
            _record_file_state(journal, journal_path, lockfile_path)
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
    return {"executed": executed, "lockfile": str(lockfile_path), "dry_run": dry_run, "transaction": txid if not dry_run else None, "journal": str(journal_path) if not dry_run else None}
