#!/usr/bin/env python3
# Purpose: Create a unique temp sandbox with a copy of a skill for safe testing.
# Created: 2026-02-20
# Last updated: 2026-09-02

"""
Create a bounded temporary staging directory containing a copy of a skill.
Source symlinks are rejected. Follows INPUT_HARDENING_STANDARD and TOOLING_POLICY.

Usage:
  create_sandbox.py --skill-path /path/to/skill/dir [--base-dir /tmp]
  create_sandbox.py --skill-name ls-pr-reviewer [--skills-root /path] [--base-dir /tmp]

Prints the skill copy path to stdout on success (one line). Use this path as
--sandbox-dir for run_smoke.py. Errors go to stderr and return non-zero.
"""

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

SKILL_NAME_MAX = 64
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
PATH_MAX = 4096
BASE_DIR_MAX = 1024
PLATFORM_PROJECTION_MAX = 256 * 1024
MARKER_NAME = ".localsetup-sandbox.json"
MARKER_MAX = 16 * 1024
MARKER_SCHEMA_VERSION = 1
FALLBACK_SKILL_ROOT_SUBPATHS = (
    "ls/skills",
    ".agents/skills",
    ".claude/skills",
    ".cursor/skills",
    ".kilo/skills",
    ".opencode/skills",
)


def _framework_repo_root(value: str) -> Path:
    candidate = Path(value).resolve()
    if (candidate / "ls" / "skills").is_dir():
        return candidate
    if candidate.name == "ls" and (candidate / "skills").is_dir():
        return candidate.parent
    return candidate


def _projection_candidates() -> list[Path]:
    candidates: list[Path] = []
    framework_dir = os.environ.get("LOCALSETUP_FRAMEWORK_DIR", "").strip()
    if framework_dir:
        root = _framework_repo_root(framework_dir)
        candidates.append(root / "ls" / "config" / "platforms.yaml")
    script = Path(__file__).resolve()
    for parent in script.parents:
        candidates.extend(
            (
                parent / "ls" / "config" / "platforms.yaml",
                parent / "config" / "platforms.yaml",
            )
        )
    return list(dict.fromkeys(candidates))


def _projection_skill_roots(path: Path) -> tuple[str, ...]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > PLATFORM_PROJECTION_MAX:
        raise ValueError("platform projection is missing, symlinked, or oversized")
    roots: list[str] = ["ls/skills"]
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped.startswith("repo_paths:"):
            continue
        value = json.loads(stripped.split(":", 1)[1].strip())
        if not isinstance(value, list):
            raise ValueError("platform repo_paths must be a list")
        for item in value:
            if (
                not isinstance(item, str)
                or not item.endswith("/skills")
                or item.startswith(("/", "~"))
                or ".." in Path(item).parts
                or len(item) > BASE_DIR_MAX
            ):
                raise ValueError("platform repo_paths contains an unsafe skill root")
            if item not in roots:
                roots.append(item)
    if len(roots) == 1:
        raise ValueError("platform projection contains no repository skill roots")
    return tuple(roots)


def _skill_root_subpaths() -> tuple[str, ...]:
    for candidate in _projection_candidates():
        try:
            return _projection_skill_roots(candidate)
        except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
            continue
    return FALLBACK_SKILL_ROOT_SUBPATHS


SKILL_ROOT_SUBPATHS = _skill_root_subpaths()


def _sanitize_skill_name(name: str) -> str:
    sanitized = (name or "").strip().replace("\x00", "")
    if len(sanitized) > SKILL_NAME_MAX:
        raise ValueError(f"skill name length exceeds {SKILL_NAME_MAX}")
    if not SKILL_NAME_PATTERN.match(sanitized) or "--" in sanitized:
        raise ValueError(
            "skill name must use lowercase letters, numbers, and single hyphens only"
        )
    return sanitized


def _sanitize_path(value: str, max_len: int = PATH_MAX) -> Path:
    if not isinstance(value, str) or len(value) > max_len:
        raise ValueError(f"path invalid or length > {max_len}")
    value = value.strip().strip("\x00").strip()
    if not value:
        raise ValueError("path is empty")
    raw = Path(value)
    if raw.is_symlink():
        raise ValueError(f"path must not be a symlink: {raw}")
    path = raw.resolve()
    if not path.exists():
        raise ValueError(f"path does not exist: {path}")
    if not path.is_dir():
        raise ValueError(f"path is not a directory: {path}")
    return path


def _resolve_skill_dir_by_name(name: str, skills_root: Path | None) -> Path:
    """Resolve a skill directory from one ordered list of known roots."""
    roots: list[Path] = []
    if skills_root and skills_root.is_dir():
        roots.append(skills_root)

    framework_dir = os.environ.get("LOCALSETUP_FRAMEWORK_DIR", "").strip()
    if framework_dir:
        roots.append(_framework_repo_root(framework_dir) / "ls" / "skills")

    cwd = Path.cwd()
    if cwd.parent.name == "skills" and cwd.is_dir():
        roots.append(cwd.parent)
    if cwd.name == "skills" and cwd.is_dir():
        roots.append(cwd)
    for base in (cwd, *cwd.parents):
        for subpath in SKILL_ROOT_SUBPATHS:
            root = base / subpath
            if root.is_dir():
                roots.append(root)

    seen: set[Path] = set()
    for root in roots:
        root = root.resolve()
        if root in seen:
            continue
        seen.add(root)
        candidate = root / name
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(
        f"skill directory not found for name '{name}' in any known skills root"
    )


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _temp_root() -> Path:
    return Path(tempfile.gettempdir()).resolve()


def _validate_base_dir(base: Path) -> Path:
    resolved = base.resolve()
    temp_root = _temp_root()
    if not _is_within(resolved, temp_root):
        raise ValueError(f"base-dir must be within platform temp root: {temp_root}")
    return resolved


def _reject_source_symlinks(source: Path) -> None:
    if source.is_symlink():
        raise ValueError(f"skill source must not be a symlink: {source}")
    for current, directories, files in os.walk(source, followlinks=False):
        current_path = Path(current)
        for name in (*directories, *files):
            candidate = current_path / name
            if candidate.is_symlink():
                raise ValueError(f"skill source contains a symlink: {candidate}")


def _write_marker(sandbox_root: Path, source: Path, skill_copy: Path) -> None:
    payload = {
        "schema_version": MARKER_SCHEMA_VERSION,
        "sandbox_dir": str(skill_copy.resolve()),
        "skill_name": source.name,
        "source_dir": str(source.resolve()),
    }
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if len(encoded.encode("utf-8")) > MARKER_MAX:
        raise ValueError("sandbox provenance marker exceeds size limit")
    (sandbox_root / MARKER_NAME).write_text(encoded, encoding="utf-8")


def _create_sandbox(skill_dir: Path, base: Path) -> Path:
    _reject_source_symlinks(skill_dir)
    source = skill_dir.resolve()
    sandbox_root = Path(
        tempfile.mkdtemp(prefix=f"skill-sandbox-{source.name}-", dir=str(base))
    )
    try:
        skill_copy = sandbox_root / source.name
        shutil.copytree(source, skill_copy, symlinks=False, dirs_exist_ok=False)
        _write_marker(sandbox_root, source, skill_copy)
        return skill_copy
    except Exception:
        shutil.rmtree(sandbox_root, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a bounded temporary copy of a skill for smoke testing."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--skill-path", metavar="DIR", help="Path to the skill directory")
    group.add_argument("--skill-name", metavar="NAME", help="Skill name (e.g. ls-pr-reviewer)")
    parser.add_argument(
        "--skills-root",
        metavar="DIR",
        help="Override skills root when using --skill-name (e.g. ls/skills)",
    )
    parser.add_argument(
        "--base-dir",
        metavar="DIR",
        help="Parent directory within platform temp (default: platform temp root)",
    )
    args = parser.parse_args()

    try:
        if args.skill_path:
            skill_dir = _sanitize_path(args.skill_path)
        else:
            name = _sanitize_skill_name(args.skill_name)
            if args.skills_root:
                skills_root = Path(str(args.skills_root)).resolve()
                if not skills_root.is_dir():
                    raise ValueError(f"skills-root is not a directory: {skills_root}")
            else:
                skills_root = None
            skill_dir = _resolve_skill_dir_by_name(name, skills_root)

        base = _temp_root()
        if args.base_dir:
            base = _sanitize_path(args.base_dir, max_len=BASE_DIR_MAX)
        base = _validate_base_dir(base)

        skill_copy = _create_sandbox(skill_dir, base)
        print(skill_copy)
        return 0
    except (ValueError, FileNotFoundError) as exc:
        print(f"create_sandbox: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"create_sandbox: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
