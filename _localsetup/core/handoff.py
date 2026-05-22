from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
from typing import Any

from .lockfile import save_text


def _stable_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _items(values: list[Any], *, field: str | None = None) -> list[str]:
    out: list[str] = []
    for value in values:
        if isinstance(value, dict) and field:
            item = value.get(field)
        else:
            item = value
        if item is None:
            continue
        out.append(str(item))
    return out


def _bullet_lines(values: list[str]) -> list[str]:
    return [f"- {value}" for value in values] if values else ["- None"]


def render_agent_prompt(payload: dict[str, Any]) -> str:
    target_root = str(payload.get("target_root") or "")
    repair_mode = str(payload.get("repair_mode") or payload.get("mode") or "migration-plan")
    detected = payload.get("detected_shape") if isinstance(payload.get("detected_shape"), dict) else {}
    inferred = payload.get("inferred") if isinstance(payload.get("inferred"), dict) else {}
    stale = detected.get("stale_framework") if isinstance(detected.get("stale_framework"), dict) else {}
    blockers = payload.get("blockers") if isinstance(payload.get("blockers"), list) else []
    decisions = payload.get("decisions") if isinstance(payload.get("decisions"), list) else []
    actions = payload.get("actions") if isinstance(payload.get("actions"), list) else []
    custom = inferred.get("custom_repo_skills") if isinstance(inferred.get("custom_repo_skills"), list) else []
    platforms = inferred.get("platforms") if isinstance(inferred.get("platforms"), list) else payload.get("platforms", [])
    commands = [
        shlex.join(
            [
                "localsetup",
                "doctor",
                "repair",
                "--target-directory",
                target_root,
                "--repair-mode",
                "migration-plan",
                "--agent-prompt",
            ]
        ),
        shlex.join(
            [
                "localsetup",
                "doctor",
                "repair",
                "--target-directory",
                target_root,
                "--repair-mode",
                "safe-repair",
                "--yes",
            ]
        ),
        shlex.join(["localsetup", "verify", "--target-directory", target_root]),
    ]
    lines = [
        "# Localsetup Repair Handoff",
        "",
        "## Target",
        "",
        f"- Path: `{target_root}`",
        f"- Status: `{payload.get('status', 'blocked' if blockers or decisions else 'unknown')}`",
        f"- Repair mode: `{repair_mode}`",
        f"- Platforms: `{', '.join(_items(platforms)) or 'none'}`",
        "",
        "## Blockers And Decisions",
        "",
    ]
    lines.extend(
        _bullet_lines(
            [f"blocker - {item}" for item in blockers]
            + [
                f"{item.get('kind', 'decision')}:{item.get('code', 'unspecified')} at {item.get('path', target_root)} - {item.get('reason', '')}"
                for item in decisions
                if isinstance(item, dict)
            ]
        )
    )
    lines.extend(["", "## Stale Framework", ""])
    if stale:
        lines.extend(
            [
                f"- Path: `{stale.get('path', '')}`",
                f"- Classification: `{stale.get('classification', 'unknown')}`",
                f"- Framework-like: `{bool(stale.get('framework_like'))}`",
                f"- Removable: `{bool(stale.get('removable'))}`",
                f"- Tracked entries: `{len(stale.get('tracked_entries', []))}`",
            ]
        )
    else:
        lines.append("- None detected")
    lines.extend(["", "## Adapter And Custom Content", ""])
    lines.extend(_bullet_lines([f"{item.get('name')} at {item.get('path')}" for item in custom if isinstance(item, dict)]))
    lines.extend(["", "## Proposed Safe Actions", ""])
    lines.extend(
        _bullet_lines(
            [
                f"{item.get('kind')} at {item.get('path')} - {item.get('reason', '')}"
                for item in actions
                if isinstance(item, dict)
            ]
        )
    )
    lines.extend(["", "## Commands", ""])
    lines.extend([f"- `{command}`" for command in commands])
    lines.extend(
        [
            "",
            "## Warnings",
            "",
            "- Preserve custom adapter content in place unless the repo owner explicitly approves migration.",
            "- Treat same-name custom adapter content as a blocker until explicitly remediated.",
            "- Do not remove protected source roots, dirty framework trees, symlinks, or custom `_localsetup/` content without review.",
        ]
    )
    return "\n".join(lines) + "\n"


def agent_prompt_payload(payload: dict[str, Any], *, path: Path | None = None, source_event_id: str | None = None) -> dict[str, Any]:
    text = render_agent_prompt(payload)
    prompt = {
        "format": "markdown",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "target_root": payload.get("target_root"),
        "text": text,
        "source_event_id": source_event_id or payload.get("event_id"),
        "context_hash": _stable_hash(
            {
                "target_root": payload.get("target_root"),
                "blockers": payload.get("blockers", []),
                "decisions": payload.get("decisions", []),
                "actions": payload.get("actions", []),
                "detected_shape": payload.get("detected_shape", {}),
                "inferred": payload.get("inferred", {}),
            }
        ),
    }
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        save_text(path, text)
        prompt["path"] = str(path)
    return prompt
