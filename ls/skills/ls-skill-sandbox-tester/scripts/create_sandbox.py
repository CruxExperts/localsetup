#!/usr/bin/env python3
# Purpose: Create a unique temp sandbox with a copy of a skill for safe testing.
# Created: 2026-02-20
# Last updated: 2026-02-20

"""
Create an isolated sandbox directory containing a copy of a skill. No symlinks;
all writes stay in the sandbox. Follows INPUT_HARDENING_STANDARD and TOOLING_POLICY.

Usage:
  create_sandbox.py --skill-path /path/to/skill/dir [--base-dir /tmp]
  create_sandbox.py --skill-name ls-pr-reviewer [--skills-root /path] [--base-dir /tmp]

Prints the skill copy path to stdout on success (one line). Use this path as --sandbox-dir for run_smoke.py. Errors to stderr, exit non-zero.
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
FALLBACK_SKILL_ROOT_SUBPATHS = (
    "ls/skills",
    ".agents/skills",
    ".claude/skills",
    ".cursor/skills",
    ".kilo/skills",
    ".opencode/skills",
)


def _projection_candidates() -> list[Path]:
    candidates: list[Path] = []
    framework_dir = os.environ.get("LOCALSETUP_FRAMEWORK_DIR", "").strip()
    if framework_dir:
        root = Path(framework_dir).resolve()
        candidates.extend((root / "config" / "platforms.yaml", root / "ls" / "config" / "platforms.yaml"))
    script = Path(__file__).resolve()
    for parent in script.parents:
        candidates.extend((parent / "ls" / "config" / "platforms.yaml", parent / "config" / "platforms.yaml"))
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
    s = (name or "").strip().replace("\x00", "")
    if len(s) > SKILL_NAME_MAX:
        raise ValueError(f"skill name length exceeds {SKILL_NAME_MAX}")
    if not SKILL_NAME_PATTERN.match(s) or "--" in s:
        raise ValueError(
            "skill name must use lowercase letters, numbers, and single hyphens only"
        )
    return s


def _sanitize_path(s: str, max_len: int = PATH_MAX) -> Path:
    if not isinstance(s, str) or len(s) > max_len:
        raise ValueError(f"path invalid or length > {max_len}")
    s = s.strip().strip("\x00").strip()
    if not s:
        raise ValueError("path is empty")
    p = Path(s).resolve()
    if not p.exists():
        raise ValueError(f"path does not exist: {p}")
    if not p.is_dir():
        raise ValueError(f"path is not a directory: {p}")
    return p


def _resolve_skill_dir_by_name(name: str, skills_root: Path | None) -> Path:
    """Resolve skill directory from name by searching common roots."""
    roots: list[Path] = []
    if skills_root and skills_root.is_dir():
        roots.append(skills_root)
    cwd = Path.cwd()
    if cwd.parent.name == "skills" and cwd.is_dir():
        roots.append(cwd.parent)
    if cwd.name == "skills" and cwd.is_dir():
        roots.append(cwd)
    for base in (cwd, *cwd.parents):
        for sub in SKILL_ROOT_SUBPATHS:
            r = base / sub
            if r.is_dir():
                roots.append(r)
    env_fw = os.environ.get("LOCALSETUP_FRAMEWORK_DIR", "").strip()
    if env_fw:
        roots.insert(0, Path(env_fw).resolve() / "skills")
    seen: set[Path] = set()
    for root in roots:
        root = root.resolve()
        if root in seen:
            continue
        seen.add(root)
        candidate = root / name
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(f"skill directory not found for name '{name}' in any known skills root")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a unique sandbox with a copy of a skill for safe testing."
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
        help="Parent directory for sandbox (default: platform temp)",
    )
    args = parser.parse_args()

    try:
        if args.skill_path:
            skill_dir = _sanitize_path(args.skill_path)
        else:
            name = _sanitize_skill_name(args.skill_name)
            skills_root = Path(args.skills_root).resolve() if args.skills_root else None
            if args.skills_root and not skills_root.is_dir():
                raise ValueError(f"skills-root is not a directory: {skills_root}")
            skill_dir = _resolve_skill_dir_by_name(name, skills_root)

        base = tempfile.gettempdir()
        if args.base_dir:
            base = _sanitize_path(args.base_dir, max_len=BASE_DIR_MAX)

        prefix = f"skill-sandbox-{skill_dir.name}-"
        sandbox_root = Path(tempfile.mkdtemp(prefix=prefix, dir=str(base)))
        skill_copy = sandbox_root / skill_dir.name
        shutil.copytree(skill_dir, skill_copy, symlinks=False, dirs_exist_ok=False)
        # Print skill copy path so run_smoke.py can use it as --sandbox-dir (cwd for commands).
        print(skill_copy)
        return 0
    except (ValueError, FileNotFoundError) as e:
        print(f"create_sandbox: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"create_sandbox: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
