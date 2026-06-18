from __future__ import annotations

from pathlib import Path
import shutil
import uuid

from .apply_journal import remove_path, write_journal
from .lockfile import save_json
from .manifests import load_pack_config
from .paths import ensure_dir
from .provenance import build_package_marker, is_managed_package, managed_marker_path
from .reference_materializer import materialize_package_artifact


def install_managed_packages(
    repo_root: Path,
    global_root: Path,
    package_names: list[str],
    source_subdir: str,
    *,
    replace_func,
    staging_root: Path | None = None,
    journal: dict | None = None,
    journal_path: Path | None = None,
) -> list[str]:
    ensure_dir(global_root)
    installed: list[str] = []
    source_root = repo_root / "_localsetup" / source_subdir
    pack = load_pack_config(repo_root)

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
                    write_journal(journal_path, journal)
            if staged.exists():
                shutil.rmtree(staged)
            staged.parent.mkdir(parents=True, exist_ok=True)
            transform_manifest = materialize_package_artifact(
                repo_root,
                src,
                staged,
                package_name=package_name,
                package_type=package_type,
                private_paths=pack.private_paths,
                emitter="package-install",
            )
            save_json(
                managed_marker_path(staged),
                {
                    **build_package_marker(
                        repo_root,
                        staged,
                        package_name=package_name,
                        package_type=package_type,
                        source_path=src,
                        emitter="package-install",
                        artifact_path=dest,
                    ),
                    "transform_manifest_digest": transform_manifest["digest"],
                },
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
                    write_journal(journal_path, journal)
            if existed:
                replace_func(dest, backup)
            replace_func(staged, dest)
        else:
            if dest.exists() or dest.is_symlink():
                remove_path(dest)
            transform_manifest = materialize_package_artifact(
                repo_root,
                src,
                dest,
                package_name=package_name,
                package_type=package_type,
                private_paths=pack.private_paths,
                emitter="package-install",
            )
            save_json(
                managed_marker_path(dest),
                {
                    **build_package_marker(
                        repo_root,
                        dest,
                        package_name=package_name,
                        package_type=package_type,
                        source_path=src,
                        emitter="package-install",
                    ),
                    "transform_manifest_digest": transform_manifest["digest"],
                },
            )
        installed.append(str(dest))

    return installed
