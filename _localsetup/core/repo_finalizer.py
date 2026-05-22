from __future__ import annotations

import fnmatch
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .git_subprocess import run_git


FINALIZER_CONFIG = "config/localsetup_finalizer.yaml"
STATE_DIR = ".localsetup/state/repo-finalizer"
SUPPORTED_CLASSIFICATIONS = {
    "managed_output",
    "generated_artifact",
    "runtime_ignored",
    "user_change",
    "unknown_change",
    "stale_legacy_framework_source",
}
MANAGED_ROOT_PREFIXES = ("_localsetup/",)


@dataclass(frozen=True)
class FinalizerSettings:
    managed_output_globs: list[str]
    generated_artifact_globs: list[str]
    runtime_ignored_globs: list[str]
    stage_allowlist_globs: list[str]


def _target(target_root: Path | None, repo_root: Path) -> Path:
    return (target_root or repo_root).expanduser().resolve()


def _defaults() -> FinalizerSettings:
    return FinalizerSettings(
        managed_output_globs=[
            ".localsetup/lock.json",
            "config/localsetup_finalizer.yaml",
            "HEARTBEAT.md",
            "config/codex_heartbeat.yaml",
            "cron/manifest.yaml",
            "cron/codex-heartbeat.crontab",
            ".codex/skills/**",
            ".claude/skills/**",
            ".cursor/skills/**",
            ".kilo/skills/**",
            ".opencode/skills/**",
            ".openclaw/skills/**",
        ],
        generated_artifact_globs=[
            "_localsetup/docs/_generated/**",
            "_localsetup/docs/_generated/*",
        ],
        runtime_ignored_globs=[
            ".localsetup/health.json",
            ".localsetup/AGENT_STATUS.md",
            ".localsetup/state/repo-finalizer",
            ".localsetup/state/repo-finalizer/",
            ".localsetup/state/repo-finalizer/**",
            ".localsetup/state/repo-finalizer/*",
            ".codex/runs",
            ".codex/runs/",
            ".codex/runs/**",
            ".codex/runs/*",
        ],
        stage_allowlist_globs=[
            ".localsetup/lock.json",
            "config/localsetup_finalizer.yaml",
            "HEARTBEAT.md",
            "config/codex_heartbeat.yaml",
            "cron/manifest.yaml",
            "cron/codex-heartbeat.crontab",
            ".codex/skills/**",
            ".claude/skills/**",
            ".cursor/skills/**",
            ".kilo/skills/**",
            ".opencode/skills/**",
            ".openclaw/skills/**",
            "_localsetup/docs/_generated/**",
            "_localsetup/docs/_generated/*",
        ],
    )


def _read_config(target_root: Path) -> dict[str, Any]:
    path = target_root / FINALIZER_CONFIG
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"finalizer config must be a mapping: {path}")
    return data


def _string_list(data: dict[str, Any], field: str, default: list[str]) -> list[str]:
    raw = data.get(field)
    if raw is None:
        return list(default)
    if not isinstance(raw, list) or not all(isinstance(item, str) and item.strip() for item in raw):
        raise ValueError(f"{field} must be a list of non-empty strings")
    return [item.strip() for item in raw]


def _settings(target_root: Path) -> FinalizerSettings:
    default = _defaults()
    data = _read_config(target_root)
    return FinalizerSettings(
        managed_output_globs=_string_list(data, "managed_output_globs", default.managed_output_globs),
        generated_artifact_globs=_string_list(data, "generated_artifact_globs", default.generated_artifact_globs),
        runtime_ignored_globs=_string_list(data, "runtime_ignored_globs", default.runtime_ignored_globs),
        stage_allowlist_globs=_string_list(data, "stage_allowlist_globs", default.stage_allowlist_globs),
    )


def _git(target_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return run_git(
        target_root,
        args,
        text=True,
        capture_output=True,
        check=False,
    )


def _git_supported(target_root: Path) -> tuple[bool, str | None]:
    probe = _git(target_root, ["rev-parse", "--is-inside-work-tree"])
    if probe.returncode != 0:
        message = (probe.stderr or probe.stdout).strip() or "not a git repository"
        return False, message
    return True, None


def _is_git_ignored(target_root: Path, path: str) -> bool:
    ignored = _git(target_root, ["check-ignore", "-q", "--", path])
    return ignored.returncode == 0


def _ensure_state_excluded(target_root: Path) -> None:
    exclude_path = _git(target_root, ["rev-parse", "--git-path", "info/exclude"])
    if exclude_path.returncode != 0:
        raise RuntimeError((exclude_path.stderr or exclude_path.stdout).strip())
    path = Path(exclude_path.stdout.strip())
    if not path.is_absolute():
        path = target_root / path
    path.parent.mkdir(parents=True, exist_ok=True)
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    entry = f"{STATE_DIR}/"
    if any(line.strip() == entry for line in current.splitlines()):
        return
    suffix = "" if not current or current.endswith("\n") else "\n"
    path.write_text(f"{current}{suffix}{entry}\n", encoding="utf-8")


def _matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def _collect_dirty(target_root: Path) -> list[dict[str, Any]]:
    status = _git(target_root, ["status", "--porcelain=1", "--untracked-files=all"])
    if status.returncode != 0:
        raise RuntimeError((status.stderr or status.stdout).strip())
    rows: list[dict[str, Any]] = []
    for raw in status.stdout.splitlines():
        if not raw:
            continue
        code = raw[:2]
        path_field = raw[3:]
        if " -> " in path_field:
            path_field = path_field.split(" -> ", 1)[1]
        renamed_or_copied = "R" in code or "C" in code
        rows.append(
            {
                "path": path_field,
                "status": code,
                "tracked": code not in {"??", "!!"},
                "ignored": code == "!!",
                "deleted": "D" in code,
                "renamed_or_copied": renamed_or_copied,
            }
        )
    return sorted(rows, key=lambda item: item["path"])


def _collect_ignored_runtime(target_root: Path, settings: FinalizerSettings, existing_paths: set[str]) -> list[dict[str, Any]]:
    status = _git(target_root, ["status", "--porcelain=1", "--ignored=matching", "--untracked-files=all"])
    if status.returncode != 0:
        raise RuntimeError((status.stderr or status.stdout).strip())
    rows: list[dict[str, Any]] = []
    for raw in status.stdout.splitlines():
        if not raw or raw[:2] != "!!":
            continue
        path_field = raw[3:]
        if path_field.endswith("/") and (target_root / path_field).is_dir():
            continue
        if path_field in existing_paths or not _matches(path_field, settings.runtime_ignored_globs):
            continue
        rows.append({"path": path_field, "status": "!!", "tracked": False, "ignored": True})
    return sorted(rows, key=lambda item: item["path"])


def _runtime_roots(patterns: list[str]) -> list[str]:
    roots: list[str] = []
    for pattern in patterns:
        wildcard_positions = [position for position in (pattern.find("*"), pattern.find("?"), pattern.find("[")) if position >= 0]
        root = pattern[: min(wildcard_positions)] if wildcard_positions else pattern
        root = root.rstrip("/")
        if not root:
            continue
        if root not in roots:
            roots.append(root)
    return roots


def _collect_disk_runtime(target_root: Path, settings: FinalizerSettings, existing_paths: set[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for root_text in _runtime_roots(settings.runtime_ignored_globs):
        root = target_root / root_text
        if not root.exists():
            continue
        paths = [root] if root.is_file() else sorted(path for path in root.rglob("*") if path.is_file())
        for path in paths:
            rel = path.relative_to(target_root).as_posix()
            if rel in existing_paths or not _matches(rel, settings.runtime_ignored_globs):
                continue
            if not _is_git_ignored(target_root, rel):
                continue
            rows.append(
                {"path": rel, "status": "!!", "tracked": False, "ignored": True, "deleted": False, "renamed_or_copied": False}
            )
    return sorted(rows, key=lambda item: item["path"])


def _classify(target_root: Path, items: list[dict[str, Any]], settings: FinalizerSettings, *, mode: str) -> list[dict[str, Any]]:
    classified: list[dict[str, Any]] = []
    for item in items:
        path = item["path"]
        tracked = bool(item["tracked"])
        deleted = bool(item.get("deleted", False))
        renamed_or_copied = bool(item.get("renamed_or_copied", False))
        actually_ignored = bool(item.get("ignored", False)) or _is_git_ignored(target_root, path)
        if _matches(path, settings.runtime_ignored_globs) and actually_ignored:
            category = "runtime_ignored"
        elif _matches(path, settings.managed_output_globs):
            category = "managed_output"
        elif _matches(path, settings.generated_artifact_globs):
            category = "generated_artifact"
        elif mode == "target" and (path == "_localsetup" or path.startswith(MANAGED_ROOT_PREFIXES)):
            category = "stale_legacy_framework_source"
        elif tracked and path.startswith(MANAGED_ROOT_PREFIXES):
            category = "unknown_change"
        elif tracked:
            category = "user_change"
        else:
            category = "unknown_change"
        action = "none"
        reason = ""
        if renamed_or_copied:
            reason = "renames and copies require explicit human review"
        elif deleted:
            reason = "deletions require explicit human review"
        elif category in {"managed_output", "generated_artifact"}:
            if _matches(path, settings.stage_allowlist_globs):
                action = "stage"
            else:
                reason = "not in stage_allowlist_globs"
        elif category == "runtime_ignored":
            reason = "runtime ignored path"
        elif category == "user_change":
            reason = "tracked user-owned change"
        elif category == "stale_legacy_framework_source":
            reason = "target _localsetup is a stale legacy framework source"
        else:
            reason = "tracked managed-root change not recognized as managed output" if tracked else "untracked path not recognized as managed output"
        classified.append(
            {
                "path": path,
                "status": item["status"],
                "ignored": actually_ignored,
                "deleted": deleted,
                "renamed_or_copied": renamed_or_copied,
                "classification": category,
                "planned_action": action,
                "blocker": renamed_or_copied
                or deleted
                or category in {"user_change", "unknown_change", "stale_legacy_framework_source"},
                "blocker_reason": reason,
            }
        )
    return classified


def _summary(files: list[dict[str, Any]]) -> dict[str, Any]:
    by_class: dict[str, int] = {key: 0 for key in SUPPORTED_CLASSIFICATIONS}
    blockers = 0
    staged_candidates = 0
    for row in files:
        by_class[row["classification"]] += 1
        blockers += 1 if row["blocker"] else 0
        staged_candidates += 1 if row["planned_action"] == "stage" else 0
    return {
        "total_dirty_files": len(files),
        "by_classification": by_class,
        "blockers": blockers,
        "stage_candidates": staged_candidates,
    }


def _diff_names(target_root: Path, *args: str) -> list[str]:
    diff = _git(target_root, ["diff", "--name-only", *args])
    if diff.returncode != 0:
        raise RuntimeError((diff.stderr or diff.stdout).strip())
    return sorted(line for line in diff.stdout.splitlines() if line)


def _snapshot(repo_root: Path, target_root: Path | None = None, *, mode: str | None = None) -> dict[str, Any]:
    target = _target(target_root, repo_root)
    selected_mode = mode or ("source" if target.resolve(strict=False) == repo_root.resolve(strict=False) else "target")
    supported, reason = _git_supported(target)
    payload: dict[str, Any] = {
        "ok": True,
        "target_root": str(target),
        "mode_classification": selected_mode,
        "config_path": str(target / FINALIZER_CONFIG),
        "state_dir": str(target / STATE_DIR),
        "git_supported": supported,
        "unsupported_reason": reason,
        "files": [],
        "summary": {
            "total_dirty_files": 0,
            "by_classification": {key: 0 for key in SUPPORTED_CLASSIFICATIONS},
            "blockers": 0,
            "stage_candidates": 0,
        },
    }
    if not supported:
        payload["ok"] = False
        payload["status"] = "unsupported"
        payload["report_only"] = True
        return payload
    settings = _settings(target)
    dirty = _collect_dirty(target)
    dirty.extend(_collect_ignored_runtime(target, settings, {item["path"] for item in dirty}))
    if not dirty:
        dirty.extend(_collect_disk_runtime(target, settings, set()))
    classified = _classify(target, dirty, settings, mode=selected_mode)
    payload["files"] = classified
    payload["summary"] = _summary(classified)
    payload["diffs"] = {
        "unstaged": _diff_names(target),
        "staged": _diff_names(target, "--cached"),
    }
    payload["settings"] = {
        "managed_output_globs": settings.managed_output_globs,
        "generated_artifact_globs": settings.generated_artifact_globs,
        "runtime_ignored_globs": settings.runtime_ignored_globs,
        "stage_allowlist_globs": settings.stage_allowlist_globs,
    }
    if payload["summary"]["total_dirty_files"] == 0:
        payload["status"] = "clean"
    elif payload["summary"]["blockers"]:
        payload["status"] = "blocked"
    elif all(row["classification"] == "runtime_ignored" for row in classified):
        payload["status"] = "clean_except_ignored"
    else:
        payload["status"] = "managed_changes"
    return payload


def _write_run_reports(payload: dict[str, Any]) -> dict[str, str]:
    state_dir = Path(payload["state_dir"])
    if payload.get("git_supported", False):
        _ensure_state_excluded(Path(payload["target_root"]))
    state_dir.mkdir(parents=True, exist_ok=True)
    report_payload = dict(payload)
    report_payload["reported_at"] = datetime.now(timezone.utc).isoformat()
    json_path = state_dir / "latest.json"
    text_path = state_dir / "latest.md"
    json_path.write_text(json.dumps(report_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    text_path.write_text(payload_to_text(report_payload), encoding="utf-8")
    return {"json": str(json_path), "text": str(text_path)}


def plan(repo_root: Path, target_root: Path | None = None, *, mode: str | None = None) -> dict[str, Any]:
    payload = _snapshot(repo_root, target_root, mode=mode)
    payload["mode"] = "plan"
    return payload


def status(repo_root: Path, target_root: Path | None = None, *, mode: str | None = None) -> dict[str, Any]:
    payload = _snapshot(repo_root, target_root, mode=mode)
    payload["mode"] = "status"
    return payload


def run(
    repo_root: Path,
    target_root: Path | None = None,
    *,
    mode: str | None = None,
    no_commit: bool = False,
    checkpoint: bool = False,
    message: str | None = None,
) -> dict[str, Any]:
    payload = _snapshot(repo_root, target_root, mode=mode)
    payload["mode"] = "run"
    payload["actions"] = []
    if not payload.get("git_supported", False):
        payload["report_only"] = True
        payload["report_paths"] = _write_run_reports(payload)
        return payload

    blockers = [row for row in payload["files"] if row["blocker"]]
    stage_paths = [row["path"] for row in payload["files"] if row["planned_action"] == "stage"]
    target = Path(payload["target_root"])
    payload["actions"].append({"kind": "evaluate", "files": len(payload["files"])})

    if no_commit:
        payload["actions"].append({"kind": "no_commit", "details": "staging and commit skipped by flag"})
        payload["took_action"] = False
        payload["checkpoint_commit"] = False
        payload["report_paths"] = _write_run_reports(payload)
        return payload

    if blockers:
        payload["ok"] = False
        payload["actions"].append({"kind": "blocked", "count": len(blockers)})
        payload["took_action"] = False
        payload["checkpoint_commit"] = False
        payload["report_paths"] = _write_run_reports(payload)
        return payload

    if stage_paths:
        add = _git(target, ["add", "--", *stage_paths])
        if add.returncode != 0:
            raise RuntimeError((add.stderr or add.stdout).strip())
        payload["actions"].append({"kind": "stage", "files": stage_paths})
    payload["took_action"] = bool(stage_paths)

    if checkpoint:
        if not message:
            raise ValueError("--checkpoint requires --message")
        if not stage_paths:
            payload["ok"] = False
            payload["actions"].append({"kind": "blocked", "reason": "no allowlisted files to commit"})
            payload["checkpoint_commit"] = False
            payload["report_paths"] = _write_run_reports(payload)
            return payload
        commit = _git(target, ["commit", "-m", message])
        if commit.returncode != 0:
            raise RuntimeError((commit.stderr or commit.stdout).strip())
        payload["actions"].append({"kind": "commit", "message": message})
        payload["checkpoint_commit"] = True
    else:
        payload["checkpoint_commit"] = False
    payload["report_paths"] = _write_run_reports(payload)
    return payload


def payload_to_text(payload: dict[str, Any]) -> str:
    lines = [
        f"mode: {payload.get('mode', 'unknown')}",
        f"target: {payload.get('target_root', '')}",
        f"git_supported: {payload.get('git_supported', False)}",
        f"status: {payload.get('status', 'unknown')}",
    ]
    summary = payload.get("summary", {})
    lines.append(f"dirty_files: {summary.get('total_dirty_files', 0)}")
    lines.append(f"blockers: {summary.get('blockers', 0)}")
    lines.append(f"stage_candidates: {summary.get('stage_candidates', 0)}")
    for row in payload.get("files", []):
        reason = f" ({row['blocker_reason']})" if row.get("blocker_reason") else ""
        lines.append(
            f"- {row['path']}: class={row['classification']} status={row['status']} "
            f"action={row['planned_action']} blocker={str(row['blocker']).lower()}{reason}"
        )
    if payload.get("actions"):
        lines.append("actions:")
        for action in payload["actions"]:
            lines.append(f"- {json.dumps(action, sort_keys=True)}")
    return "\n".join(lines) + "\n"
