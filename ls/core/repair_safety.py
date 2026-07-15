"""Safety classification helpers for repair workflows."""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any

from .adapters import ADAPTER_MARKER_JSON
from .git_state import inspect_path
from .provenance import is_managed_package
from .shell import shell_registration_status

def ls_owned_adapter_dir(source_root: Path, path: Path, decisions: list[dict]) -> bool:
    if not path.is_dir() or path.is_symlink():
        return False
    unmanaged: list[str] = []
    for child in sorted(path.iterdir()):
        if child.name in {ADAPTER_MARKER_JSON, ".localsetup-portable"}:
            continue
        if child.name.startswith("."):
            unmanaged.append(child.name)
            continue
        if child.is_dir() and not child.is_symlink() and is_managed_package(child):
            continue
        unmanaged.append(child.name)
    if unmanaged:
        decisions.append(
            {
                "kind": "adapter_content",
                "path": str(path),
                "reason": "adapter directory contains non-Localsetup files",
                "values": unmanaged,
                "required": "move or classify this content before applying repair",
            }
        )
        return False
    return True

def _symlink_target_under_managed_roots(path: Path, managed_roots: list[Path]) -> bool:
    if not path.is_symlink():
        return False
    link_target = path.readlink()
    if not link_target.is_absolute():
        link_target = path.parent / link_target
    resolved_target = link_target.resolve(strict=False)
    for root in managed_roots:
        resolved_root = root.resolve(strict=False)
        if resolved_target == resolved_root:
            return True
        try:
            resolved_target.relative_to(resolved_root)
            return True
        except ValueError:
            continue
    return False

def _framework_source_like(path: Path) -> bool:
    return (path / "config" / "pack.yaml").is_file() and (path / "core").is_dir()

def _relative_file_set(path: Path) -> set[str]:
    if not path.is_dir() or path.is_symlink():
        return set()
    files: set[str] = set()
    for child in path.rglob("*"):
        if child.is_dir():
            continue
        try:
            rel = child.relative_to(path).as_posix()
        except ValueError:
            continue
        files.add(rel)
    return files

def _differing_files(left: Path, right: Path, rel_paths: set[str]) -> list[str]:
    differing: list[str] = []
    for rel in sorted(rel_paths):
        try:
            if (left / rel).read_bytes() != (right / rel).read_bytes():
                differing.append(rel)
        except OSError:
            differing.append(rel)
    return differing

def _source_root_like(path: Path) -> bool:
    framework = path / "ls"
    return (
        _framework_source_like(framework)
        and (path / "VERSION").is_file()
        and ((path / "pyproject.toml").is_file() or (path / "install").is_file())
    )

def _is_tracked(target_root: Path, path: Path) -> bool:
    try:
        rel = path.relative_to(target_root)
    except ValueError:
        return False
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", str(rel)],
        cwd=target_root,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0

def _classify_stale_framework(source_root: Path, home: Path, target_root: Path, protected_reasons: list[str]) -> dict[str, Any]:
    path = target_root / "ls"
    exists = path.exists() or path.is_symlink()
    git_state = inspect_path(target_root, "ls") if exists else {
        "supported": False,
        "tracked_entries": [],
        "staged_entries": [],
        "unstaged_entries": [],
        "untracked_entries": [],
        "ignored_entries": [],
        "status_entries": [],
        "clean": False,
        "dirty": False,
        "error": None,
    }
    info: dict[str, Any] = {
        "path": str(path),
        "classification": "absent",
        "framework_like": False,
        "protected": False,
        "git_state": git_state,
        "tracked_entries": git_state.get("tracked_entries", []),
        "unknown_entries": [],
        "removable": False,
        "required_mode": None,
        "evidence": [],
    }
    if not exists or source_root.resolve(strict=False) == target_root.resolve(strict=False):
        return info
    if protected_reasons:
        info.update(
            {
                "classification": "protected_source_root",
                "protected": True,
                "evidence": protected_reasons,
            }
        )
        return info
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        info.update({"classification": "unsafe_framework_node", "evidence": ["ls is not a directory"]})
        return info
    if not _framework_source_like(path):
        unknown = []
        if path.is_dir():
            unknown = sorted(child.name for child in path.iterdir() if not child.name.startswith("."))
        info.update(
            {
                "classification": "custom_framework_content",
                "unknown_entries": unknown,
                "evidence": ["ls does not match Localsetup framework source shape"],
            }
        )
        return info
    target_files = _relative_file_set(path)
    source_framework = source_root / "ls"
    source_files = _relative_file_set(source_framework)
    extra_files = sorted(target_files - source_files)
    modified_files = _differing_files(path, source_framework, target_files & source_files)
    if extra_files or modified_files:
        info.update(
            {
                "classification": "custom_framework_content",
                "framework_like": True,
                "unknown_entries": extra_files,
                "modified_entries": modified_files,
                "evidence": ["framework-shaped ls differs from the current Localsetup source tree"],
            }
        )
        return info
    tracked = bool(git_state.get("tracked_entries"))
    dirty = bool(
        git_state.get("staged_entries")
        or git_state.get("unstaged_entries")
        or (tracked and git_state.get("untracked_entries"))
    )
    info["framework_like"] = True
    if dirty:
        info.update(
            {
                "classification": "dirty_stale_framework",
                "required_mode": "migration-plan",
                "evidence": ["Git reports staged, unstaged, or mixed untracked changes under ls"],
            }
        )
        return info
    if tracked:
        info.update(
            {
                "classification": "clean_tracked_stale_framework",
                "removable": True,
                "required_mode": "safe-repair",
                "evidence": ["tracked ls is framework-like and clean"],
            }
        )
        return info
    info.update(
        {
            "classification": "untracked_stale_framework",
            "removable": True,
            "required_mode": "safe-repair",
            "evidence": ["untracked ls is framework-like"],
        }
    )
    return info

def _protected_source_roots(source_root: Path, home: Path) -> list[dict]:
    roots: list[dict] = [
        {"path": source_root.resolve(strict=False), "reason": "active source root"},
        {
            "path": (home / ".local" / "share" / "localsetup" / "source").resolve(strict=False),
            "reason": "default managed Localsetup source checkout",
        },
    ]
    shell_status = shell_registration_status(source_root, home=home)
    recorded_source = shell_status.get("source_root")
    if recorded_source:
        roots.append(
            {
                "path": Path(str(recorded_source)).expanduser().resolve(strict=False),
                "reason": "registered Localsetup shell source checkout",
            }
        )
    deduped: list[dict] = []
    seen: set[str] = set()
    for item in roots:
        key = str(item["path"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped

def _protected_target_reasons(source_root: Path, home: Path, target_root: Path) -> list[str]:
    resolved_target = target_root.resolve(strict=False)
    reasons = [
        item["reason"]
        for item in _protected_source_roots(source_root, home)
        if Path(item["path"]).resolve(strict=False) == resolved_target
    ]
    if _source_root_like(target_root):
        reasons.append("target looks like a Localsetup maintainer/source checkout")
    return sorted(set(reasons))
