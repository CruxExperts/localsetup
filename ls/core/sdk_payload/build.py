"""Setuptools mapping from the single canonical source to private wheel data."""
from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import shutil

from setuptools.command.build_py import build_py

# Setuptools loads cmdclass files before the source package is importable.
# Load the sibling standard-library verifier directly, without runtime imports.
_spec = spec_from_file_location("_localsetup_sdk_build_integrity", Path(__file__).with_name("integrity.py"))
if _spec is None or _spec.loader is None:
    raise RuntimeError("Cannot load SDK build verifier")
_integrity = module_from_spec(_spec)
_spec.loader.exec_module(_integrity)
verify = _integrity.verify


class BuildSDK(build_py):
    """Copy only validated SDK files; never install their public import names."""

    def run(self) -> None:
        if self.editable_mode:
            super().run()
            return
        source = Path(__file__).resolve().parents[3] / "vendor" / "lscli"
        manifest = verify(source)
        build_root = Path(self.build_lib).absolute()
        destination = build_root / "ls" / "_sdk_payload"
        for path in (*build_root.parents, build_root, build_root / "ls", destination):
            if path.is_symlink():
                raise ValueError("SDK build destination must not contain symlinks")
        if destination.exists():
            previous = verify(destination)
            if previous != manifest:
                raise ValueError("Stale SDK build payload: use a fresh build output directory")
        super().run()
        destination.mkdir(parents=True, exist_ok=True)
        for name in ["manifest.json", *sorted(manifest["files"])]:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, target)
        if verify(destination) != manifest:
            raise ValueError("SDK build payload changed during copying")

    def get_outputs(self, include_bytecode: bool = True) -> list[str]:
        outputs = super().get_outputs(include_bytecode=include_bytecode)
        destination = Path(self.build_lib) / "ls" / "_sdk_payload"
        if destination.is_dir():
            manifest = verify(destination)
            outputs.extend(str(destination / name) for name in ["manifest.json", *manifest["files"]])
        return outputs
