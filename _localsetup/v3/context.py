from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import InstallConfig, config_to_dict
from .dependencies import dependency_status
from .doctor import run_doctor
from .migration import detect_legacy_artifacts
from .plan import build_install_plan


def _action_dicts(plan_actions) -> list[dict[str, Any]]:
    return [{"kind": action.kind, "path": str(action.path), "details": action.details} for action in plan_actions]


def build_agent_context(repo_root: Path, *, home: Path, config: InstallConfig) -> dict:
    target_root = Path(config.target_directory).expanduser().resolve() if config.target_directory else None
    plan = build_install_plan(
        repo_root,
        home=home,
        packs=config.packs,
        attach_mode=config.attach_mode,
        platform_ids=config.platforms,
        target_root=target_root,
    )
    doctor = run_doctor(
        repo_root,
        home=home,
        packs=config.packs,
        platform_ids=config.platforms,
        dependency_mode=config.dependency_mode,
        target_root=target_root,
    )
    dependencies = dependency_status(repo_root, mode=config.dependency_mode).to_dict()
    selected_platforms = plan.rollback_metadata.get("platforms", [])
    selected_packs = plan.rollback_metadata.get("packs", config.packs)
    migration_artifacts = detect_legacy_artifacts(repo_root, home=home, platform_ids=config.platforms, target_root=target_root)

    commands = {
        "doctor": "python3 _localsetup/tools/localsetup_v3.py doctor",
        "plan": "python3 _localsetup/tools/localsetup_v3.py plan",
        "install": "python3 _localsetup/tools/localsetup_v3.py install --apply",
        "verify": "python3 _localsetup/tools/localsetup_v3.py verify",
        "rollback": "python3 _localsetup/tools/localsetup_v3.py rollback",
    }
    suffix_parts: list[str] = []
    if config.target_directory:
        suffix_parts.extend(["--target-directory", config.target_directory])
    if config.platforms:
        suffix_parts.extend(["--platforms", *config.platforms])
    if suffix_parts:
        suffix = " " + " ".join(suffix_parts)
        commands = {key: value + suffix for key, value in commands.items()}

    return {
        "environment": doctor["environment"],
        "config": config_to_dict(config),
        "selected_platforms": selected_platforms,
        "selected_packs": selected_packs,
        "dependencies": dependencies,
        "migration": {
            "mode": config.migration_mode,
            "artifacts": migration_artifacts,
            "backup_dir": config.backup_dir,
        },
        "actions": _action_dicts(plan.actions),
        "blockers": doctor["blockers"],
        "warnings": doctor["warnings"],
        "commands": commands,
        "rollback": plan.rollback_metadata,
        "verification": [
            "python3 -m pytest _localsetup/tests",
            "./_localsetup/tests/automated_test.sh",
            "python3 _localsetup/tools/localsetup_v3.py validate-catalog",
            "python3 _localsetup/tools/localsetup_v3.py scan-migration",
        ],
    }


def render_markdown_report(context: dict) -> str:
    lines = [
        "# Localsetup v3 Install Context",
        "",
        f"- Repo: `{context['environment']['repo_root']}`",
        f"- Home: `{context['environment']['home']}`",
        f"- Platforms: {', '.join(context['selected_platforms']) or 'none'}",
        f"- Packs: {', '.join(context['selected_packs']) or 'none'}",
        f"- Dependency mode: `{context['dependencies']['mode']}`",
        "",
        "## Blockers",
        "",
    ]
    blockers = context.get("blockers") or []
    lines.extend([f"- {item}" for item in blockers] or ["- None"])
    lines.extend(["", "## Warnings", ""])
    warnings = context.get("warnings") or []
    lines.extend([f"- {item}" for item in warnings] or ["- None"])
    lines.extend(["", "## Planned Actions", ""])
    for action in context.get("actions", []):
        lines.append(f"- `{action['kind']}` -> `{action['path']}`")
    if not context.get("actions"):
        lines.append("- None")
    lines.extend(["", "## Commands", ""])
    for key, value in context.get("commands", {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Verification", ""])
    for command in context.get("verification", []):
        lines.append(f"- `{command}`")
    return "\n".join(lines) + "\n"
