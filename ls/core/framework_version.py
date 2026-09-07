from __future__ import annotations

from importlib import metadata
from pathlib import Path
import tomllib

from .versioning_models import SemVer


def _framework_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _source_version_path() -> Path | None:
    root = _framework_root()
    pyproject = root / "pyproject.toml"
    version_file = root / "VERSION"
    if not pyproject.is_file() or not version_file.is_file():
        return None
    project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {})
    if project.get("name") != "localsetup":
        return None
    return version_file


def framework_version() -> str:
    """Return the canonical source version or installed distribution version."""
    source_version = _source_version_path()
    if source_version is not None:
        raw_version = source_version.read_text(encoding="utf-8").strip()
    else:
        try:
            raw_version = metadata.version("localsetup")
        except metadata.PackageNotFoundError as exc:
            raise RuntimeError("unable to determine LocalSetup version") from exc
    try:
        return str(SemVer.parse(raw_version))
    except ValueError as exc:
        raise RuntimeError(f"invalid LocalSetup version: {raw_version!r}") from exc
