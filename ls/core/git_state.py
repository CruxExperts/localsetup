from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any


def git_status_snapshot(root: Path) -> dict:
    probe = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if probe.returncode != 0:
        return {
            "supported": False,
            "entries": [],
            "raw": "",
            "error": (getattr(probe, "stderr", "") or getattr(probe, "stdout", "") or "").strip(),
        }
    status = subprocess.run(
        ["git", "status", "--short"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    raw = getattr(status, "stdout", "") if status.returncode == 0 else ""
    entries = []
    for line in raw.splitlines():
        if not line:
            continue
        entries.append({"status": line[:2], "path": line[3:] if len(line) > 3 else line})
    return {
        "supported": True,
        "entries": entries,
        "raw": raw,
        "error": None if status.returncode == 0 else getattr(status, "stderr", "").strip(),
    }


def _git_supported(root: Path) -> tuple[bool, str | None]:
    probe = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if probe.returncode != 0:
        return False, (probe.stderr or probe.stdout or "").strip()
    return True, None


def _status_entries(root: Path, path: str) -> list[dict[str, str]]:
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all", "--", path],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if status.returncode != 0:
        return []
    entries: list[dict[str, str]] = []
    for line in status.stdout.splitlines():
        if not line:
            continue
        raw_path = line[3:] if len(line) > 3 else ""
        if " -> " in raw_path:
            before, after = raw_path.split(" -> ", 1)
            paths = [before, after]
        else:
            paths = [raw_path]
        for item in paths:
            entries.append({"status": line[:2], "path": item})
    return entries


def inspect_path(root: Path, path: str) -> dict[str, Any]:
    """Return a path-scoped Git status summary safe for repair decisions."""
    supported, error = _git_supported(root)
    if not supported:
        return {
            "supported": False,
            "path": path,
            "tracked_entries": [],
            "staged_entries": [],
            "unstaged_entries": [],
            "untracked_entries": [],
            "ignored_entries": [],
            "status_entries": [],
            "clean": False,
            "dirty": False,
            "error": error,
        }
    tracked = subprocess.run(
        ["git", "ls-files", "--", path],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    ignored = subprocess.run(
        ["git", "ls-files", "--ignored", "--exclude-standard", "--others", "--", path],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    entries = _status_entries(root, path)
    staged = [entry for entry in entries if entry["status"][0] not in {" ", "?"}]
    unstaged = [entry for entry in entries if entry["status"][1] not in {" ", "?"}]
    untracked = [entry for entry in entries if entry["status"] == "??"]
    tracked_entries = [line for line in tracked.stdout.splitlines() if line]
    return {
        "supported": True,
        "path": path,
        "tracked_entries": tracked_entries,
        "staged_entries": staged,
        "unstaged_entries": unstaged,
        "untracked_entries": untracked,
        "ignored_entries": [line for line in ignored.stdout.splitlines() if line] if ignored.returncode == 0 else [],
        "status_entries": entries,
        "clean": bool(tracked_entries) and not entries,
        "dirty": bool(entries),
        "error": None,
    }


def git_untrack_path(root: Path, path: str, *, dry_run: bool = False) -> dict[str, Any]:
    if path.strip("/\\") != "ls":
        raise ValueError("git_untrack_path is restricted to ls")
    args = ["git", "rm", "-r", "--cached", "--dry-run" if dry_run else "--", path]
    if dry_run:
        args = ["git", "rm", "-r", "--cached", "--dry-run", "--", path]
    result = subprocess.run(args, cwd=root, text=True, capture_output=True, check=False)
    return {
        "ok": result.returncode == 0,
        "path": path,
        "dry_run": dry_run,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
    }


def status_delta(before: dict, after: dict, planned_paths: list[str]) -> dict:
    before_paths = {entry["path"] for entry in before.get("entries", []) if isinstance(entry, dict)}
    planned = tuple(path.strip("/") for path in planned_paths if path)
    created = []
    pre_existing = []
    classified = []
    for entry in after.get("entries", []):
        if not isinstance(entry, dict):
            continue
        path = str(entry.get("path", ""))
        category = "user_change"
        if path in before_paths:
            pre_existing.append(entry)
        elif planned and any(path == item or path.startswith(item + "/") for item in planned):
            created.append(entry)
            if path == ".localsetup/lock.json":
                category = "managed_output"
            elif path in {".localsetup/health.json", ".localsetup/AGENT_STATUS.md"} or path.startswith(
                (
                    ".localsetup/install-journal/",
                    ".localsetup/backups/",
                    ".localsetup/state/",
                    ".localsetup/context-index/",
                )
            ):
                category = "runtime_ignored"
            elif path == "ls" or path.startswith("ls/"):
                category = "stale_framework_removed"
            else:
                category = "managed_output"
        else:
            pre_existing.append(entry)
        classified.append({**entry, "classification": category})
    return {
        "supported": bool(before.get("supported") and after.get("supported")),
        "pre_existing_changes": pre_existing,
        "localsetup_created_changes": created,
        "classified_entries": classified,
    }
