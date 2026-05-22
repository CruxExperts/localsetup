from __future__ import annotations

from pathlib import Path
import subprocess


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


def status_delta(before: dict, after: dict, planned_paths: list[str]) -> dict:
    before_paths = {entry["path"] for entry in before.get("entries", []) if isinstance(entry, dict)}
    planned = tuple(path.strip("/") for path in planned_paths if path)
    created = []
    pre_existing = []
    for entry in after.get("entries", []):
        if not isinstance(entry, dict):
            continue
        path = str(entry.get("path", ""))
        if path in before_paths:
            pre_existing.append(entry)
        elif planned and any(path == item or path.startswith(item + "/") for item in planned):
            created.append(entry)
        else:
            pre_existing.append(entry)
    return {
        "supported": bool(before.get("supported") and after.get("supported")),
        "pre_existing_changes": pre_existing,
        "localsetup_created_changes": created,
    }
