from __future__ import annotations

from pathlib import Path

from _localsetup.core.git_subprocess import run_git

from .models import FileMetric


FRAMEWORK_PREFIXES = (
    "_localsetup/core/",
    "_localsetup/tools/",
    "_localsetup/lib/",
)
SKILL_PREFIX = "_localsetup/skills/"
EXCLUDED_PARTS = {
    ".venv",
    ".localsetup",
    ".localsetup-maint",
    ".codex",
    ".cache",
    ".pytest_cache",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}


def tracked_python_paths(repo_root: Path, include_scope: str) -> list[str]:
    completed = run_git(
        repo_root,
        ["ls-files", "-z", "*.py"],
        check=False,
        capture_output=True,
        text=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git ls-files failed: {stderr}")

    paths: list[str] = []
    for raw_path in completed.stdout.split(b"\0"):
        path = raw_path.decode("utf-8", errors="replace").strip()
        if not path:
            continue
        parts = set(Path(path).parts)
        if parts & EXCLUDED_PARTS:
            continue
        if include_scope in {"framework", "all"} and path.startswith(FRAMEWORK_PREFIXES):
            paths.append(path)
            continue
        if include_scope in {"skills", "all"} and path.startswith(SKILL_PREFIX):
            paths.append(path)
    return sorted(set(paths))


def line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8", errors="replace").splitlines())


def scan_files(repo_root: Path, include_scope: str) -> list[FileMetric]:
    metrics: list[FileMetric] = []
    for rel_path in tracked_python_paths(repo_root, include_scope):
        absolute_path = repo_root / rel_path
        if absolute_path.is_file():
            metrics.append(FileMetric(path=rel_path, line_count=line_count(absolute_path), absolute_path=absolute_path))
    return metrics
