from __future__ import annotations

from pathlib import Path
import shutil

from .lockfile import save_json
from .manifests import load_pack_config
from .models import DeployPlan
from .paths import ensure_dir, repo_path
from .adapters import adapter_path_state
from .source import source_commit


def _install_managed_packages(
    repo_root: Path,
    global_root: Path,
    package_names: list[str],
    source_subdir: str,
) -> list[str]:
    ensure_dir(global_root)
    installed: list[str] = []
    source_root = repo_root / "_localsetup" / source_subdir

    for package_name in sorted(package_names):
        src = source_root / package_name
        dest = global_root / package_name
        if dest.exists() and not (dest / ".localsetup-managed").exists():
            raise RuntimeError(f"refusing to overwrite unmanaged package path: {dest}")
        if dest.exists() or dest.is_symlink():
            if dest.is_symlink() or dest.is_file():
                dest.unlink()
            else:
                shutil.rmtree(dest)
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
    for action in plan.actions:
        if action.kind == "ensure_dir":
            if not dry_run:
                ensure_dir(action.path)
            executed.append(f"ensure_dir:{action.path}")
        elif action.kind == "write_registry":
            if not dry_run:
                ensure_dir(action.path.parent)
                save_json(
                    action.path,
                    {
                        "managed_by": "localsetup-v3",
                        "source_commit": source_commit(repo_root),
                        **action.details,
                    },
                )
            executed.append(f"write_registry:{action.path}")
        elif action.kind == "install_skills":
            if not dry_run:
                installed_skills = _install_managed_skills(repo_root, action.path, action.details["skills"])
            executed.append(f"install_skills:{action.path}")
        elif action.kind == "install_workflows":
            if not dry_run:
                installed_workflows = _install_managed_workflows(repo_root, action.path, action.details["workflows"])
            executed.append(f"install_workflows:{action.path}")
        elif action.kind == "attach_repo_path":
            if not dry_run:
                ensure_dir(action.path.parent)
                mode = action.details.get("mode", "symlink")
                global_root = Path(action.details["global_root"])
                state = adapter_path_state(action.path, global_root)
                if action.path.exists() or action.path.is_symlink():
                    if state["collision_reason"]:
                        raise RuntimeError(f"refusing to replace {state['collision_reason']} at adapter path: {action.path}")
                    if action.path.is_dir() and not action.path.is_symlink():
                        shutil.rmtree(action.path)
                    elif action.path.is_symlink() and mode == "symlink":
                        executed.append(f"attach_repo_path:{action.path}")
                        continue
                    else:
                        action.path.unlink()
                if mode == "portable":
                    shutil.copytree(global_root, action.path)
                    (action.path / ".localsetup-portable").write_text("managed_by=localsetup-v3\n", encoding="utf-8")
                else:
                    action.path.symlink_to(global_root)
            executed.append(f"attach_repo_path:{action.path}")

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
    }
    if not dry_run:
        save_json(lockfile_path, lock_payload)
    return {"executed": executed, "lockfile": str(lockfile_path), "dry_run": dry_run}
