from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest
from setuptools import Distribution

from ls.core.sdk_payload.build import BuildSDK
from ls.core.sdk_payload.integrity import verify

ROOT = Path(__file__).resolve().parents[2]


def command(tmp_path: Path) -> BuildSDK:
    distribution = Distribution({"packages": ["ls"], "package_dir": {"ls": str(ROOT / "ls")}})
    distribution.script_name = "setup.py"
    build = BuildSDK(distribution)
    build.ensure_finalized()
    build.build_lib = str(tmp_path / "output")
    return build


def test_build_retains_exact_private_payload_and_repeats_cleanly(tmp_path):
    build = command(tmp_path)
    build.run()
    private = Path(build.build_lib) / "ls" / "_sdk_payload"
    assert verify(private) == verify(ROOT / "vendor/lscli")
    assert not (Path(build.build_lib) / "pydantic_ai").exists()
    assert str(private / "manifest.json") in build.get_outputs()
    build.run()


@pytest.mark.parametrize("mutation", ["extra", "changed", "symlink"])
def test_reused_build_output_rejects_substitution(tmp_path, mutation):
    build = command(tmp_path)
    build.run()
    private = Path(build.build_lib) / "ls" / "_sdk_payload"
    if mutation == "extra":
        (private / "extra.py").write_text("pass")
    elif mutation == "changed":
        (private / "pydantic_ai/__init__.py").write_text("changed")
    else:
        (private / "extra").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        build.run()


def test_editable_framework_build_does_not_supply_sdk(tmp_path):
    build = command(tmp_path)
    build.editable_mode = True
    build.run()
    assert not (Path(build.build_lib) / "ls" / "_sdk_payload").exists()


def test_core_preserves_lazy_main_export_without_runtime_imports():
    code = "import sys; sys.path.insert(0, sys.argv[1]); import ls.core; from ls.core.sdk_payload.integrity import verify; assert 'ls.core.cli' not in sys.modules; assert 'yaml' not in sys.modules"
    subprocess.run([sys.executable, "-I", "-S", "-c", code, str(ROOT)], check=True)
    import ls.core
    from ls.core.cli import main

    assert ls.core.main is main
