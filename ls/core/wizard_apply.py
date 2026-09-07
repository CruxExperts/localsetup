"""Wizard apply and interruption handling."""

from __future__ import annotations

from .apply import apply_plan
from .dependencies import ensure_dependencies
from .plan import build_install_plan
from .shell import register_shell_command
from .verify import verify_install
from .wizard_catalog import _detach_prior_adapters, _global_pack_defaults, _global_root
from .wizard_models import TerminalWizard, WizardState

def _apply_and_show_result(term: TerminalWizard, state: WizardState) -> int:
    term.title("Applying")
    target_root = state.target_directory
    platforms = state.platforms or []
    global_packs, global_preset = _global_pack_defaults(state)
    repo_packs = state.repo_packs if state.repo_packs is not None else (state.packs if platforms and state.packs is not None else [])
    try:
        dependency_info = (
            ensure_dependencies(
                state.repo_root,
                mode=state.dependency_mode,
                data_root=state.home / ".local" / "share" / "localsetup",
                target_root=target_root,
            )
            if state.dependency_mode != "prompt-only"
            else None
        )
        plan = build_install_plan(
            state.repo_root,
            home=state.home,
            packs=state.packs,
            preset=state.preset,
            skills=state.skills,
            workflows=state.workflows,
            skill_classes=state.skill_classes,
            skill_tags=state.skill_tags,
            exclude_skills=state.exclude_skills,
            global_packs=global_packs,
            global_preset=global_preset,
            global_skills=state.global_skills,
            global_workflows=state.global_workflows,
            global_skill_classes=state.global_skill_classes,
            global_skill_tags=state.global_skill_tags,
            global_exclude_skills=state.global_exclude_skills,
            repo_packs=repo_packs,
            repo_preset=state.repo_preset,
            repo_skills=state.repo_skills,
            repo_workflows=state.repo_workflows,
            repo_skill_classes=state.repo_skill_classes,
            repo_skill_tags=state.repo_skill_tags,
            repo_exclude_skills=state.repo_exclude_skills,
            attach_mode=state.attach_mode,
            platform_ids=platforms,
            target_root=target_root,
        )
        result = apply_plan(
            state.repo_root,
            plan,
            home=state.home,
            dry_run=False,
            dependency_info=dependency_info,
            target_root=target_root,
        )
        shell_result = register_shell_command(state.repo_root, home=state.home) if state.register_shell else None
        detached_adapters = _detach_prior_adapters(state) if state.detach_repo_setup else []
        verify = verify_install(state.repo_root, state.home, platform_ids=platforms, target_root=target_root)
    except Exception as exc:
        term.status_line("fail", "Install failed.")
        term.detail_line(str(exc), style="error")
        term.diagnostic_command(
            [
                "python3",
                str(state.repo_root / "ls/tools/localsetup.py"),
                "--home",
                str(state.home),
                "--source-root",
                str(state.repo_root),
                "doctor",
            ]
        )
        return 2

    term.title("Result")
    term.detail_line("Decides: Confirms what was installed and which follow-up commands are useful.")
    if verify["ok"]:
        term.status_line("ok", "LocalSetup installed successfully.")
    else:
        term.status_line("warn", "Install finished, but verification reported issues.")
    term.key_value_block(
        [
            ("Managed library", str(_global_root(state.repo_root, state.home))),
            ("Target", str(target_root or state.repo_root)),
            ("Platforms", ", ".join(platforms) if platforms else "none"),
        ]
    )
    if shell_result:
        term.key_value_block([("Command", str(state.home / ".local/bin/localsetup"))])
        for warning in shell_result.get("warnings", []):
            term.status_line("warn", warning)
    term.write("")
    term.write("Next commands:")
    verify_cmd = ["localsetup", "verify"]
    if platforms:
        verify_cmd.extend(["--tools", ",".join(platforms)])
    term.detail_line(" ".join(verify_cmd), indent="  ", style="command")
    term.detail_line("localsetup rollback", indent="  ", style="command")
    if result.get("lockfile"):
        term.key_value_block([("Lockfile", str(result["lockfile"]))])
    if detached_adapters:
        term.key_value_block([("Detached adapters", ", ".join(detached_adapters))])
    if term.detail_mode:
        term.detail_line("Does: Verification checked the managed library and selected adapter paths after applying the plan.")
        term.detail_line("Choose when: Use the verify command later if you move files or change installed platforms.")
        term.detail_line("Tradeoff: Rollback uses the lockfile from this run, so keep it with the prepared repo.")
    return 0 if verify["ok"] else 1

def _write_interrupted_message(term: TerminalWizard, *, apply_started: bool) -> None:
    term.write("")
    if apply_started:
        term.write(
            "Install interrupted during apply. Some changes may have been applied; "
            "run localsetup verify or rollback before retrying."
        )
    else:
        term.write("Install canceled. No changes were applied.")
