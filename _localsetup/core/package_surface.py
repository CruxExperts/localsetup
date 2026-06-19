from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from .manifests import load_pack_config
from .paths import expand_user_path
from .reference_materializer import materialize_package_artifact, validate_materialized_package


def validate_package_surfaces(repo_root: Path, *, home: Path) -> dict[str, Any]:
    root = repo_root.expanduser().resolve(strict=False)
    pack = load_pack_config(root)
    package_root = expand_user_path(pack.package_root, home).expanduser().resolve(strict=False)
    issues: list[str] = []
    packages: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="localsetup-package-surface-") as tmp:
        temp_root = Path(tmp)
        for source_subdir, package_type in (("skills", "skill"), ("workflows", "workflow")):
            source_root = root / "_localsetup" / source_subdir
            if not source_root.is_dir():
                continue
            for source in sorted(path for path in source_root.iterdir() if path.is_dir() and path.name.startswith("ls-")):
                destination = temp_root / source_subdir / source.name
                try:
                    materialize_package_artifact(
                        root,
                        source,
                        destination,
                        package_name=source.name,
                        package_type=package_type,
                        private_paths=pack.private_paths,
                        home=home,
                        runtime_package_root=package_root,
                        emitter="package-surface-validation",
                    )
                    validation = validate_materialized_package(destination, repo_root=root, home=home, runtime_package_root=package_root)
                except Exception as exc:
                    validation = {"ok": False, "issues": [str(exc)]}
                if not validation["ok"]:
                    issues.extend(f"{source_subdir}/{source.name}: {issue}" for issue in validation["issues"])
                packages.append(
                    {
                        "package": source.name,
                        "type": package_type,
                        "source": str(source.relative_to(root)),
                        "ok": bool(validation["ok"]),
                        "issues": validation["issues"],
                    }
                )
    return {"ok": not issues, "issues": issues, "packages": packages}
