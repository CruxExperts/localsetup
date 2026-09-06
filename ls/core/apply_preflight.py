from __future__ import annotations

from pathlib import Path

from .adapters import adapter_path_state, legacy_global_roots
from .provenance import is_managed_package

SAFE_ADAPTER_STATUS_CODES = {
    "absent",
    "custom_repo_skills",
    "managed_scoped_adapter",
    "managed_portable_adapter",
    "legacy_monolithic_symlink",
    "mixed_managed_custom_adapter",
    "shared_adapter_directory",
}


def unsafe_same_name_adapter_entries(action, state: dict) -> list[str]:
    selected = {str(name) for name in action.details.get("packages", [])}
    unsafe = set(state.get("custom_entries", [])) | set(state.get("unknown_entries", []))
    return sorted(selected & unsafe)


def codex_agent_source(repo_root: Path, agent_name: str) -> Path:
    return repo_root / "ls" / "adapters" / "codex" / "agents" / f"{agent_name}.toml"


def preflight_install_plan(repo_root: Path, plan, home: Path, *, target_root: Path | None = None) -> dict:
    blockers: list[dict] = []
    from .personal_registry import validate_personal_selection_consistency
    try:
        validate_personal_selection_consistency([
            action.details for action in plan.actions if action.kind == "attach_personal_path"
        ])
    except ValueError as exc:
        blockers.append({"path": str(target_root or repo_root),
                         "status_code": "personal_selection_conflict", "reason": str(exc)})
    repo_paths = {action.path for action in plan.actions if action.kind == "attach_repo_path"}
    personal_paths = {action.path for action in plan.actions if action.kind == "attach_personal_path"}
    for path in sorted(repo_paths & personal_paths):
        blockers.append({"path": str(path), "status_code": "overlapping_scope_actions",
                         "reason": "one install cannot write the same adapter through both scopes"})
    for action in plan.actions:
        if action.kind == "attach_personal_path":
            from .personal_adapter import selection
            try:selection(repo_root, home, action)
            except (ValueError, OSError) as exc:
                blockers.append({"path": str(action.path), "status_code": "personal_adapter_unsafe", "reason": str(exc)})
            continue
        if action.kind in {"install_skills", "install_workflows"}:
            source_subdir = "skills" if action.kind == "install_skills" else "workflows"
            names = action.details.get("skills", action.details.get("workflows", []))
            for name in names:
                src = repo_root / "ls" / source_subdir / str(name)
                dest = action.path / str(name)
                if not src.is_dir():
                    blockers.append(
                        {"path": str(src), "status_code": "missing_source_package", "reason": "selected package source is missing"}
                    )
                elif dest.exists() and not is_managed_package(dest):
                    blockers.append(
                        {
                            "path": str(dest),
                            "status_code": "unmanaged_package_path",
                            "reason": "refusing to overwrite unmanaged package path",
                        }
                    )
        elif action.kind == "install_codex_agents":
            for name in action.details.get("agents", []):
                src = codex_agent_source(repo_root, str(name))
                dest = action.path / f"{name}.toml"
                if not src.is_file():
                    blockers.append(
                        {"path": str(src), "status_code": "missing_source_agent", "reason": "selected Codex agent source is missing"}
                    )
                    continue
                if dest.is_symlink() or (dest.exists() and not dest.is_file()):
                    blockers.append(
                        {
                            "path": str(dest),
                            "status_code": "codex_agent_conflict",
                            "reason": "refusing to overwrite existing Codex agent path that is not a regular file",
                        }
                    )
                    continue
                if dest.is_file():
                    try:
                        existing = dest.read_text(encoding="utf-8")
                    except (OSError, UnicodeDecodeError) as exc:
                        blockers.append(
                            {
                                "path": str(dest),
                                "status_code": "codex_agent_conflict",
                                "reason": f"refusing to overwrite unreadable existing Codex agent file: {exc}",
                            }
                        )
                        continue
                    if existing == src.read_text(encoding="utf-8"):
                        continue
                    blockers.append(
                        {
                            "path": str(dest),
                            "status_code": "codex_agent_conflict",
                            "reason": "refusing to overwrite existing Codex agent file with different content",
                        }
                    )
        elif action.kind == "attach_repo_path":
            from .personal_registry import refuse_personal_overlap
            from .registry import load_registry
            from .manifests import load_pack_config
            from .paths import expand_user_path
            registry = load_registry(expand_user_path(load_pack_config(repo_root).global_registry, home))
            try:refuse_personal_overlap(registry, [str(action.path)])
            except ValueError as exc:
                blockers.append({"path": str(action.path), "status_code": "personal_owner_overlap", "reason": str(exc)})
                continue
            global_root = Path(action.details["global_root"])
            state = adapter_path_state(
                action.path,
                global_root,
                known_global_roots=legacy_global_roots(home),
                target_root=target_root,
            )
            if state["status_code"] not in SAFE_ADAPTER_STATUS_CODES:
                blockers.append(
                    {
                        "path": str(action.path),
                        "status_code": state["status_code"],
                        "reason": state["collision_reason"] or "adapter target is not safe to mutate",
                    }
                )
                continue
            unsafe_entries = unsafe_same_name_adapter_entries(action, state)
            if unsafe_entries:
                blockers.append(
                    {
                        "path": str(action.path),
                        "status_code": "adapter_custom_package_name_collision",
                        "reason": "adapter contains custom or unknown entries with selected LocalSetup package names",
                        "entries": unsafe_entries,
                    }
                )
        elif action.kind == "retire_historical_adapter":
            global_root = Path(action.details["global_root"])
            state = adapter_path_state(
                action.path,
                global_root,
                known_global_roots=legacy_global_roots(home),
                target_root=target_root,
            )
            platform = str(action.details.get("platform", "unknown"))
            if action.path.exists() and not action.path.is_symlink() and not action.path.is_dir():
                blockers.append(
                    {
                        "path": str(action.path),
                        "status_code": "unsupported_historical_adapter_node",
                        "reason": f"historical {platform} adapter is not a supported symlink or directory",
                    }
                )
            elif action.path.is_symlink() and not (
                state["points_to_global"]
                or state["points_to_legacy_global"]
                or state.get("managed_visible_packages")
            ):
                blockers.append(
                    {
                        "path": str(action.path),
                        "status_code": (
                            "unproven_legacy_codex_symlink"
                            if platform == "codex"
                            else f"unproven_historical_{platform}_symlink"
                        ),
                        "reason": (
                            f"historical {action.path} symlink is not proven LocalSetup-managed; "
                            f"preserve it and review or remove it before installing the {platform} adapter"
                        ),
                    }
                )
    return {"ok": not blockers, "blockers": blockers}
