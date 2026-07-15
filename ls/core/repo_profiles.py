from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .git_subprocess import run_git
from .lockfile import save_text


UNIVERSAL_AGENT_REPO_PROFILE = "universal-agent-repo"
REPO_PROFILES = {UNIVERSAL_AGENT_REPO_PROFILE}


@dataclass(frozen=True)
class ProfileFile:
    relative_path: str
    content: str
    description: str


def render_repo_profile(
    profile: str,
    target_root: Path,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    target_root = target_root.expanduser().resolve()
    if profile != UNIVERSAL_AGENT_REPO_PROFILE:
        return {
            "ok": False,
            "profile": profile,
            "target_root": str(target_root),
            "applied": False,
            "actions": [],
            "blockers": [f"unknown repo profile: {profile}"],
            "warnings": [],
        }

    files = _universal_agent_repo_files()
    actions: list[dict[str, Any]] = []
    blockers: list[str] = []
    warnings: list[str] = []

    for item in files:
        path = target_root / item.relative_path
        action = {
            "kind": "write_file",
            "path": str(path),
            "relative_path": item.relative_path,
            "description": item.description,
            "sha256": _sha256_text(item.content),
        }
        if path.exists():
            existing = path.read_text(encoding="utf-8")
            if existing == item.content:
                action["status"] = "unchanged"
            else:
                action["status"] = "blocked"
                blockers.append(f"refusing to overwrite existing file with different content: {item.relative_path}")
        else:
            action["status"] = "create"
        actions.append(action)

    exclude_action = _git_exclude_action(target_root)
    if exclude_action:
        actions.append(exclude_action)

    ok = not blockers
    if apply and ok:
        target_root.mkdir(parents=True, exist_ok=True)
        for item in files:
            path = target_root / item.relative_path
            if path.exists():
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            save_text(path, item.content)
        if exclude_action and exclude_action["status"] == "append":
            exclude_path = Path(exclude_action["path"])
            exclude_path.parent.mkdir(parents=True, exist_ok=True)
            with exclude_path.open("a", encoding="utf-8") as handle:
                handle.write(".codex/runs/\n")
    elif apply and not ok:
        warnings.append("apply skipped because blockers were found")

    return {
        "ok": ok,
        "profile": profile,
        "target_root": str(target_root),
        "applied": bool(apply and ok),
        "actions": actions,
        "blockers": blockers,
        "warnings": warnings,
    }


def _git_exclude_action(target_root: Path) -> dict[str, Any] | None:
    if not target_root.exists():
        return None
    probe = run_git(target_root, ["rev-parse", "--is-inside-work-tree"], text=True, capture_output=True, check=False)
    if probe.returncode != 0:
        return None
    result = run_git(target_root, ["rev-parse", "--git-path", "info/exclude"], text=True, capture_output=True, check=False)
    if result.returncode != 0:
        return None
    exclude = Path(result.stdout.strip())
    if not exclude.is_absolute():
        exclude = target_root / exclude
    status = "append"
    if exclude.exists():
        lines = exclude.read_text(encoding="utf-8").splitlines()
        if ".codex/runs/" in lines:
            status = "unchanged"
    return {
        "kind": "git_info_exclude",
        "path": str(exclude),
        "relative_path": ".git/info/exclude",
        "description": "Ignore private Codex run ledgers in this checkout",
        "entry": ".codex/runs/",
        "status": status,
    }


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _universal_agent_repo_files() -> list[ProfileFile]:
    return [
        ProfileFile(
            "AGENTS.md",
            _agents_md(),
            "Shared agent instructions for the repository",
        ),
        ProfileFile(
            "agent-repo-shape.json",
            _agent_repo_shape_json(),
            "Machine-readable description of the universal agent repo shape",
        ),
        ProfileFile(
            "external_skills.lock.json",
            _external_skills_lock_json(),
            "Reviewed external skill lockfile placeholder",
        ),
        ProfileFile(
            "docs/INDEX.md",
            _docs_index_md(),
            "Human-readable documentation index",
        ),
        ProfileFile(
            "docs/index.yaml",
            _docs_index_yaml(),
            "Machine-readable documentation index",
        ),
        ProfileFile(
            "docs/reference/agent-repo-shape.md",
            _agent_repo_shape_md(),
            "Reference for the repo shape contract",
        ),
    ]


def _agents_md() -> str:
    return """# Agent Instructions

This repository uses the universal agent repo shape.

## Operating Rules

- Treat `AGENTS.md` as the shared repo instruction entrypoint.
- Keep private run state under `.codex/runs/`; do not commit it.
- Keep durable project documentation under `docs/`.
- Review external skills before adding them to `external_skills.lock.json`.
- Prefer small, verifiable changes with focused tests or checks.
"""


def _agent_repo_shape_json() -> str:
    return """{
  "schema_version": 1,
  "profile": "universal-agent-repo",
  "instructions": {
    "shared": "AGENTS.md"
  },
  "docs": {
    "index": "docs/INDEX.md",
    "machine_index": "docs/index.yaml",
    "reference": "docs/reference/agent-repo-shape.md"
  },
  "skills": {
    "external_lock": "external_skills.lock.json",
    "shared_repo_skills": ".agents/skills"
  },
  "private_state": [
    ".codex/runs/"
  ]
}
"""


def _external_skills_lock_json() -> str:
    return """{
  "schema_version": 1,
  "skills": []
}
"""


def _docs_index_md() -> str:
    return """# Documentation Index

## Reference

- [Agent repo shape](reference/agent-repo-shape.md)
"""


def _docs_index_yaml() -> str:
    return """version: 1
documents:
  - id: agent-repo-shape
    title: Agent repo shape
    path: docs/reference/agent-repo-shape.md
"""


def _agent_repo_shape_md() -> str:
    return """# Agent Repo Shape

The universal agent repo shape keeps shared agent instructions, documentation,
and reviewed skill metadata in stable repository paths.

## Required Files

- `AGENTS.md`: shared repository instructions.
- `agent-repo-shape.json`: machine-readable shape metadata.
- `external_skills.lock.json`: reviewed external skill roster.
- `docs/INDEX.md`: human-readable documentation index.
- `docs/index.yaml`: machine-readable documentation index.
- `docs/reference/agent-repo-shape.md`: this reference.

## Private State

Use `.codex/runs/` for private run ledgers and other transient agent state.
When the target is a Git repository, Localsetup adds `.codex/runs/` to
`.git/info/exclude` instead of modifying tracked ignore files.
"""
