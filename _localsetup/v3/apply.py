from __future__ import annotations

from pathlib import Path
import shutil

from .lockfile import save_json
from .manifests import load_pack_config
from .models import DeployPlan
from .paths import ensure_dir, repo_path
from .source import source_commit


def _install_managed_skills(repo_root: Path, global_root: Path, skill_names: list[str]) -> list[str]:
    ensure_dir(global_root)
    installed: list[str] = []
    skills_root = repo_root / "_localsetup" / "skills"

    for skill_name in sorted(skill_names):
        src = skills_root / skill_name
        dest = global_root / skill_name
        if dest.exists() and not (dest / ".localsetup-managed").exists():
            raise RuntimeError(f"refusing to overwrite unmanaged skill path: {dest}")
        if dest.exists() or dest.is_symlink():
            if dest.is_symlink() or dest.is_file():
                dest.unlink()
            else:
                shutil.rmtree(dest)
        shutil.copytree(src, dest)
        (dest / ".localsetup-managed").write_text(f"source={skill_name}\n", encoding="utf-8")
        installed.append(str(dest))

    return installed


def apply_plan(
    repo_root: Path,
    plan: DeployPlan,
    home: Path,
    dry_run: bool = False,
    dependency_info: dict | None = None,
) -> dict:
    executed: list[str] = []
    installed_skills: list[str] = []
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
        elif action.kind == "attach_repo_path":
            if not dry_run:
                ensure_dir(action.path.parent)
                mode = action.details.get("mode", "symlink")
                if action.path.exists() or action.path.is_symlink():
                    if action.path.is_dir() and not action.path.is_symlink():
                        if mode != "portable" or not (action.path / ".localsetup-portable").exists():
                            raise RuntimeError(f"refusing to replace non-symlink adapter path: {action.path}")
                        shutil.rmtree(action.path)
                    else:
                        action.path.unlink()
                if mode == "portable":
                    shutil.copytree(Path(action.details["global_root"]), action.path)
                    (action.path / ".localsetup-portable").write_text("managed_by=localsetup-v3\n", encoding="utf-8")
                else:
                    action.path.symlink_to(Path(action.details["global_root"]))
            executed.append(f"attach_repo_path:{action.path}")

    pack = load_pack_config(repo_root)
    lockfile_path = repo_path(repo_root, pack.lockfile, "repo.lockfile")
    lock_payload = {
        "version": 1,
        "pack": pack.pack_id,
        "namespace": pack.namespace,
        "source_commit": source_commit(repo_root),
        "aliases": plan.rollback_metadata.get("aliases", {}),
        "skills": plan.rollback_metadata.get("skills", []),
        "adapter_state": [s for s in plan.rollback_metadata.get("repo_links", [])],
        "platforms": plan.rollback_metadata.get("platforms", []),
        "attach_mode": plan.rollback_metadata.get("attach_mode", "symlink"),
        "installed_skills": installed_skills,
        "dependency_mode": (dependency_info or {}).get("mode"),
        "python_interpreter": (dependency_info or {}).get("interpreter"),
    }
    if not dry_run:
        save_json(lockfile_path, lock_payload)
    return {"executed": executed, "lockfile": str(lockfile_path), "dry_run": dry_run}
