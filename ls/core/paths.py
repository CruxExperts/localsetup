from __future__ import annotations

from pathlib import Path
import re

from .models import GlobalLayout, SourceLayout, TargetLayout


class PathValidationError(ValueError):
    pass


_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def _normalized_parts(path_str: str, field: str) -> list[str]:
    raw = str(path_str).strip()
    if not raw:
        raise PathValidationError(f"{field} must not be empty")
    if "\x00" in raw:
        raise PathValidationError(f"{field} contains a NUL byte: {path_str!r}")
    if _WINDOWS_DRIVE_RE.match(raw):
        raise PathValidationError(f"{field} must not use an absolute Windows path: {path_str}")
    normalized = raw.replace("\\", "/")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise PathValidationError(f"{field} must not contain empty, current, or parent path segments: {path_str}")
    return parts


def validate_repo_relative_path(path_str: str, field: str = "repo path") -> str:
    raw = str(path_str).strip()
    if Path(raw).is_absolute() or raw.startswith("~"):
        raise PathValidationError(f"{field} must be repo-relative: {path_str}")
    _normalized_parts(raw, field)
    return raw


def validate_home_scoped_path(path_str: str, field: str = "home path") -> str:
    raw = str(path_str).strip()
    if not raw.startswith("~/"):
        raise PathValidationError(f"{field} must be scoped under the user home with ~/: {path_str}")
    _normalized_parts(raw[2:], field)
    return raw


def repo_path(repo_root: Path, path_str: str, field: str = "repo path") -> Path:
    rel = validate_repo_relative_path(path_str, field)
    root = repo_root.resolve()
    candidate = root / rel
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise PathValidationError(f"{field} escapes repository root: {path_str}") from exc
    try:
        candidate.parent.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise PathValidationError(f"{field} parent escapes repository root: {path_str}") from exc
    return candidate


def expand_user_path(path_str: str, home: Path | None = None) -> Path:
    validate_home_scoped_path(path_str)
    if path_str.startswith("~/"):
        if home is None:
            return Path(path_str).expanduser()
        return home / path_str[2:]
    return Path(path_str)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def source_layout(source_root: Path) -> SourceLayout:
    root = source_root.expanduser().resolve(strict=False)
    framework = root / "ls"
    if not framework.exists():
        raise PathValidationError(f"source_root must contain ls: {root}")
    return SourceLayout(source_root=root)


def global_layout(home: Path, *, package_root: str | None = None, registry_path: str | None = None) -> GlobalLayout:
    localsetup_home = home.expanduser().resolve(strict=False) / ".local" / "share" / "localsetup"
    package = expand_user_path(package_root, home) if package_root else localsetup_home / "packages"
    registry = expand_user_path(registry_path, home) if registry_path else localsetup_home / "registry.json"
    return GlobalLayout(
        localsetup_home=localsetup_home,
        package_root=package.expanduser().resolve(strict=False),
        registry_path=registry.expanduser().resolve(strict=False),
    )


def target_layout(target_root: Path) -> TargetLayout:
    return TargetLayout(target_root=target_root.expanduser().resolve(strict=False))


def target_lockfile_path(target_root: Path) -> Path:
    return target_layout(target_root).lockfile_path


def legacy_target_lockfile_path(target_root: Path) -> Path:
    return target_layout(target_root).legacy_lockfile_path


def target_journal_root(target_root: Path) -> Path:
    return target_layout(target_root).journal_root


def target_backup_root(target_root: Path) -> Path:
    return target_layout(target_root).backup_root
