from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from ls.core import framework_version as version_module


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "ls" / "tools" / "localsetup.py"


@pytest.mark.parametrize("flag", ["--version", "-V"])
def test_cli_version_flags_print_canonical_version(flag: str) -> None:
    expected = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

    result = subprocess.run(
        [sys.executable, str(CLI), flag],
        cwd=ROOT.parent,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout == f"LocalSetup {expected}\n"
    assert result.stderr == ""


def test_framework_version_prefers_canonical_source_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    version_file = tmp_path / "VERSION"
    version_file.write_text("9.8.7\n", encoding="utf-8")
    monkeypatch.setattr(version_module, "_source_version_path", lambda: version_file)

    def unexpected_distribution_lookup(name: str) -> str:
        raise AssertionError(f"unexpected distribution lookup: {name}")

    monkeypatch.setattr(version_module.metadata, "version", unexpected_distribution_lookup)

    assert version_module.framework_version() == "9.8.7"


def test_framework_version_uses_distribution_metadata_when_source_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(version_module, "_source_version_path", lambda: None)
    monkeypatch.setattr(version_module.metadata, "version", lambda name: "7.6.5" if name == "localsetup" else "")

    assert version_module.framework_version() == "7.6.5"


def test_framework_version_ignores_unverified_root_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "VERSION").write_text("1.2.3\n", encoding="utf-8")
    monkeypatch.setattr(version_module, "_framework_root", lambda: tmp_path)
    monkeypatch.setattr(version_module.metadata, "version", lambda name: "7.6.5" if name == "localsetup" else "")

    assert version_module.framework_version() == "7.6.5"


@pytest.mark.parametrize("value", ["", "not-a-version", "4.2.18\nextra"])
def test_framework_version_rejects_invalid_source_values(
    value: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    version_file = tmp_path / "VERSION"
    version_file.write_text(value, encoding="utf-8")
    monkeypatch.setattr(version_module, "_source_version_path", lambda: version_file)

    with pytest.raises(RuntimeError, match="invalid LocalSetup version"):
        version_module.framework_version()


def test_framework_version_fails_clearly_when_no_version_source_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(version_module, "_source_version_path", lambda: None)

    def missing_distribution(name: str) -> str:
        raise version_module.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(version_module.metadata, "version", missing_distribution)

    with pytest.raises(RuntimeError, match="unable to determine LocalSetup version"):
        version_module.framework_version()
