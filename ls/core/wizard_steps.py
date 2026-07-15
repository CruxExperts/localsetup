"""Wizard step rendering and review planning."""

from __future__ import annotations

import os
from pathlib import Path

from .doctor import run_doctor
from .plan import build_install_plan
from .selection import recommended_packs_for_target, resolve_package_selection
from .wizard_catalog import (
    _action_summary,
    _attach_choices,
    _dependency_choices,
    _global_pack_defaults,
    _global_root,
    _pack_choices,
    _platform_choices,
    _skill_choices,
    _skill_class_choices,
    _skill_tag_choices,
    _source_identity,
)
from .wizard_models import BACK, CANCEL, WELCOME_BANNER, Choice, TerminalWizard, WizardState
from .wizard_selection import (
    _blocker_prompt,
    _confirm_apply,
    _continue_prompt,
    _target_directory_prompt,
    choose_many_checkbox,
    choose_one,
)

def _show_welcome(term: TerminalWizard, state: WizardState) -> str:
    term.banner(WELCOME_BANNER)
    term.write("")
    term.title("Source and Release")
    term.detail_line("Decides: Confirms the installer source and release channel before package choices.")
    term.detail_line("This wizard installs the managed Localsetup package library and can attach repo adapters for agent tools.")
    latest_ref = os.environ.get("LOCALSETUP_BOOTSTRAP_LATEST_REF") or "not checked"
    release_status = os.environ.get("LOCALSETUP_BOOTSTRAP_RELEASE_STATUS") or "explicit/local source"
    term.key_value_block(
        [
            ("Source checkout", str(state.repo_root)),
            ("Source ref", _source_identity(state.repo_root)),
            ("Latest upstream", latest_ref),
            ("Release check", release_status),
            ("Managed library", str(_global_root(state.repo_root, state.home))),
        ]
    )
    term.status_line("info", "It will show a review screen before anything is applied.")
    return _continue_prompt(
        term,
        "Press Enter to continue",
        help_text="This first screen only orients you. Nothing changes until the Review screen is applied.",
        detail_text="Localsetup keeps a managed shared library under your home directory and can optionally attach repo adapter paths.",
    )

def _source_step(term: TerminalWizard, state: WizardState) -> str:
    term.title("Source")
    term.detail_line("Decides: Which Localsetup checkout provides the installer files and shipped skills.")
    term.key_value_block([("Using Localsetup source", str(state.repo_root))])
    term.detail_line("Explicit --directory values are used as-is; raw installs use the managed source checkout.")
    if term.detail_mode:
        term.detail_line("Does: Reads manifests, skills, workflows, and installer code from this checkout.")
        term.detail_line("Choose when: This source path is the Localsetup version you want to install from.")
        term.detail_line("Tradeoff: A stale source checkout can install stale skills; refresh the source first if that is a concern.")
    return _continue_prompt(
        term,
        "Press Enter to continue",
        help_text="Source is informational here. Use b to return from the next step or q to cancel before applying.",
        detail_text="The source checkout is not modified by this step.",
    )

def _mode_step(term: TerminalWizard, state: WizardState) -> str:
    term.title("Repo Setup")
    choices = [
        Choice(
            "none",
            "No repo setup",
            "Updates the managed Localsetup package library without repo adapter paths.",
            "On reruns, removes only prior managed adapter paths while leaving the shared library intact.",
            "You only want the shared package library refreshed right now.",
            "No `.agents/skills` or other repo adapter paths are created.",
        ),
        Choice(
            "current",
            f"Current directory ({state.caller_directory})",
            "Prepares the current folder for selected agent tools.",
            "Installs the managed library and attaches adapter paths inside the current directory.",
            "You are standing in the repo you want Codex, Cursor, or another tool to use.",
            "Creates repo-local adapter paths for the selected platforms.",
        ),
        Choice(
            "other",
            "Another target directory",
            "Prepares a different repo while using this source checkout.",
            "Prompts for a target path, then attaches selected platform adapters there.",
            "You launched the installer from one location but want to wire a different repository.",
            "You must enter the target path correctly before the review step.",
        ),
    ]
    default = "none"
    if state.target_directory_is_explicit and state.target_directory is not None:
        choices = [
            choices[0],
            Choice(
                "explicit",
                f"Target directory ({state.target_directory})",
                "Uses the target path already provided on the command line.",
                "Installs the managed library and attaches adapters to the explicit target directory.",
                "You intentionally passed --target-directory and want that path prepared.",
                "Creates adapter paths in the explicit target, not necessarily the current directory.",
            ),
            choices[1],
            choices[2],
        ]
        default = "explicit"
    elif (not state.target_directory_is_explicit and state.target_directory is not None) or state.platforms:
        default = "current"
    choice = choose_one(
        term,
        "Repo setup",
        choices,
        default=default,
        decides="Whether this run only refreshes the managed library or also wires a repo adapter.",
        suggested_reason="This matches the command-line context and avoids surprising repo changes.",
        help_text="Pick no repo setup for the least invasive install, current for this repo, or another target when preparing a different path.",
    )
    if choice in {BACK, CANCEL}:
        return choice
    if choice == "none":
        state.detach_repo_setup = bool(state.prior_target_directory and state.prior_adapter_targets)
        state.target_directory = state.prior_target_directory if state.detach_repo_setup else None
        state.platforms = []
    elif choice == "current":
        state.target_directory = state.caller_directory
        if not state.platforms:
            state.platforms = ["codex"]
    elif choice == "explicit":
        if state.platforms_were_provided and not state.platforms:
            state.platforms = ["codex"]
    else:
        answer = _target_directory_prompt(term)
        if answer in {BACK, CANCEL}:
            return answer
        state.target_directory = Path(answer).expanduser().resolve()
        if not state.platforms:
            state.platforms = ["codex"]
    return "continue"

def _platform_step(term: TerminalWizard, state: WizardState) -> str:
    if state.detach_repo_setup:
        state.platforms = []
        state.repo_packs = []
        return "continue"
    if state.target_directory is None:
        state.platforms = []
        state.repo_packs = []
        return "continue"
    term.title("Repo Adapters")
    default_platforms = state.platforms or (["codex"] if not state.target_directory_is_explicit else [])
    selected = choose_many_checkbox(
        term,
        "Select platforms",
        _platform_choices(state.repo_root),
        default=default_platforms,
        allow_none=True,
        decides="Which agent tool adapter paths are created in the target repo.",
        suggested_reason="Codex is the default when wiring a repo unless a platform was provided already.",
        help_text="Select one or more agent tools. Each selected platform creates the adapter path shown in its row.",
    )
    if isinstance(selected, str) and selected in {BACK, CANCEL}:
        return selected
    state.platforms = selected
    if not selected:
        state.repo_packs = []
        return "continue"
    default_packs = state.repo_packs if state.repo_packs is not None else state.packs
    if default_packs is None:
        if state.repo_preset is not None or state.preset is not None:
            default_packs = resolve_package_selection(
                state.repo_root,
                preset=state.repo_preset or state.preset,
                skills=state.repo_skills if state.repo_skills is not None else state.skills,
                skill_classes=state.repo_skill_classes if state.repo_skill_classes is not None else state.skill_classes,
                skill_tags=state.repo_skill_tags if state.repo_skill_tags is not None else state.skill_tags,
                exclude_skills=state.repo_exclude_skills if state.repo_exclude_skills is not None else state.exclude_skills,
                target_root=state.target_directory,
            ).packs
        else:
            default_packs = recommended_packs_for_target(state.target_directory)
            state.repo_preset = "suggested"
    repo_selected = choose_many_checkbox(
        term,
        "Select repo-visible packs",
        _pack_choices(state.repo_root),
        default=default_packs,
        allow_none=True,
        decides="Which packages are visible through this repo's selected adapter paths.",
        suggested_reason="Detected repo suggestions are used unless a prior lockfile or CLI selector is present.",
        help_text="Repo-visible packs are exposed through adapter paths. The managed library also keeps the global baseline selected earlier.",
    )
    if isinstance(repo_selected, str) and repo_selected in {BACK, CANCEL}:
        return repo_selected
    state.repo_packs = repo_selected
    if state.repo_preset is None:
        state.repo_preset = state.preset or ("core" if repo_selected == ["core"] else "custom")
    return "continue"

def _pack_step(term: TerminalWizard, state: WizardState) -> str:
    term.title("Global Package Library")
    default_packs = state.global_packs if state.global_packs is not None else state.packs
    if default_packs is None:
        default_packs, inferred_global_preset = _global_pack_defaults(state)
        if inferred_global_preset == "normal" and state.global_preset is None:
            state.global_preset = "normal"
    selected = choose_many_checkbox(
        term,
        "Select global packs",
        _pack_choices(state.repo_root),
        default=default_packs,
        allow_none=True,
        decides="Which baseline packages are kept in the managed Localsetup library.",
        suggested_reason="Normal is the default global baseline unless prior registry settings or CLI selectors are present.",
        help_text="Choose one or more packs for the shared package library. Repo adapter visibility is selected separately.",
    )
    if isinstance(selected, str) and selected in {BACK, CANCEL}:
        return selected
    if set(selected) == set(default_packs):
        selected = default_packs
    state.global_packs = selected
    if state.global_preset is None:
        state.global_preset = state.preset or ("core" if selected == ["core"] else "custom")
    return "continue"

def _skill_group_step(term: TerminalWizard, state: WizardState) -> str:
    term.title("Skill Groups")
    classes = choose_many_checkbox(
        term,
        "Select skill classes",
        _skill_class_choices(state.repo_root),
        default=state.skill_classes or [],
        allow_none=True,
        decides="Which taxonomy classes add skills beyond selected packs.",
        suggested_reason="Leave this empty unless you want a broad class-level addition.",
        help_text="Classes are additive. Use the next screen to toggle individual skills before apply.",
    )
    if isinstance(classes, str) and classes in {BACK, CANCEL}:
        return classes
    tags = choose_many_checkbox(
        term,
        "Select skill tags",
        _skill_tag_choices(state.repo_root),
        default=state.skill_tags or [],
        allow_none=True,
        decides="Which tagged skills add to the install footprint.",
        suggested_reason="Leave this empty unless a tag matches your repo need.",
        help_text="Tags are additive. Use the next screen to remove individual skills you do not want.",
    )
    if isinstance(tags, str) and tags in {BACK, CANCEL}:
        return tags
    state.skill_classes = classes
    state.skill_tags = tags
    return "continue"

def _skill_individual_step(term: TerminalWizard, state: WizardState) -> str:
    term.title("Individual Skills")
    target_root = state.target_directory or state.caller_directory
    base = resolve_package_selection(
        state.repo_root,
        packs=state.packs,
        preset=state.preset,
        skills=state.skills,
        workflows=state.workflows,
        skill_classes=state.skill_classes,
        skill_tags=state.skill_tags,
        exclude_skills=state.exclude_skills,
        target_root=target_root,
    )
    selected = choose_many_checkbox(
        term,
        "Toggle skills",
        _skill_choices(state.repo_root),
        default=base.skills,
        allow_none=False,
        decides="The exact skill packages included after pack, class, and tag selection.",
        suggested_reason="The prechecked set comes from the selected preset, packs, classes, and tags.",
        help_text="Use Space to toggle individual skills. Workflow-required skills may be re-added during planning.",
    )
    if isinstance(selected, str) and selected in {BACK, CANCEL}:
        return selected
    state.skills = selected
    state.exclude_skills = sorted(set(base.skills) - set(selected))
    return "continue"

def _options_step(term: TerminalWizard, state: WizardState) -> str:
    term.title("Options")
    attach = choose_one(
        term,
        "Adapter mode",
        _attach_choices(),
        default=state.attach_mode,
        decides="How repo adapter paths point at the installed skill library.",
        suggested_reason="Symlinks are easiest to keep updated.",
        help_text="Symlink keeps repo adapters pointed at the managed library. Portable copies make the repo more self-contained.",
    )
    if attach in {BACK, CANCEL}:
        return attach
    deps = choose_one(
        term,
        "Dependency mode",
        _dependency_choices(),
        default=state.dependency_mode,
        decides="Whether the installer only reports dependencies or prepares Localsetup's Python environment.",
        suggested_reason="Prompt-only avoids changing host dependencies during a first install.",
        help_text="Prompt-only reports needs without installing. uv-sync prepares Localsetup's project .venv.",
    )
    if deps in {BACK, CANCEL}:
        return deps
    state.attach_mode = attach
    state.dependency_mode = deps
    return "continue"

def _review_step(term: TerminalWizard, state: WizardState) -> str:
    term.title("Review")
    term.detail_line("Decides: Whether the planned install should be applied.")
    target_root = state.target_directory
    platforms = state.platforms or []
    global_packs, global_preset = _global_pack_defaults(state)
    repo_packs = state.repo_packs if state.repo_packs is not None else (state.packs if platforms and state.packs is not None else [])
    plan = build_install_plan(
        state.repo_root,
        home=state.home,
        packs=state.packs,
        preset=state.preset,
        skills=state.skills,
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
    doctor = run_doctor(
        state.repo_root,
        home=state.home,
        packs=global_packs,
        platform_ids=platforms,
        dependency_mode=state.dependency_mode,
        target_root=target_root,
    )
    term.write("Source")
    term.key_value_block(
        [
            ("Checkout", str(state.repo_root)),
            ("Home library", str(_global_root(state.repo_root, state.home))),
        ],
        indent="  ",
    )
    term.write("")
    term.write("Target")
    term.key_value_block(
        [
            ("Directory", f"{target_root or state.repo_root} ({'global library only' if not platforms else 'adapters selected'})"),
            ("Adapter mode", state.attach_mode),
        ],
        indent="  ",
    )
    term.write("")
    term.write("Selections")
    term.key_value_block(
        [
            ("Platforms", ", ".join(platforms) if platforms else "none"),
            ("Global packs", ", ".join(plan.rollback_metadata.get("global_baseline_packs", [])) or "none"),
            ("Repo packs", ", ".join(plan.rollback_metadata.get("repo_packs", [])) if platforms else "none"),
            ("Global packages", str(len(plan.rollback_metadata.get("global_baseline_packages", [])))),
            ("Repo-visible packages", str(len(plan.rollback_metadata.get("repo_packages", []))) if platforms else "0"),
            ("Installed skills", str(len(plan.rollback_metadata.get("skills", [])))),
            ("Installed workflows", str(len(plan.rollback_metadata.get("workflows", [])))),
            ("Dependency mode", state.dependency_mode),
        ],
        indent="  ",
    )
    if term.detail_mode:
        term.detail_line("Does: Shows source, target, packs, adapter mode, dependency mode, and concrete filesystem actions before changes.")
        term.detail_line("Choose when: Continue only if this screen matches the install you intended.")
        term.detail_line("Tradeoff: Going back is cheap now; after apply, rollback uses the generated lockfile.")
    term.write("")
    term.write("Planned actions:")
    term.action_list(_action_summary(plan.actions))
    if doctor["warnings"]:
        term.write("")
        term.write(term.token("Warnings:", "warning"))
        for warning in doctor["warnings"]:
            term.status_line("warn", warning)
    if doctor["blockers"]:
        term.write("")
        term.write(term.token("Blockers:", "blocker"))
        for blocker in doctor["blockers"]:
            term.status_line("fail", blocker)
        cmd = [
            "python3",
            str(state.repo_root / "ls/tools/localsetup.py"),
            "--home",
            str(state.home),
            "--source-root",
            str(state.repo_root),
        ]
        if target_root:
            cmd.extend(["--target-directory", str(target_root)])
        cmd.extend(["doctor", "--dependency-mode", state.dependency_mode])
        if global_packs:
            cmd.extend(["--global-packs", *global_packs])
        if repo_packs:
            cmd.extend(["--repo-packs", *repo_packs])
        if platforms:
            cmd.extend(["--platforms", *platforms])
        term.diagnostic_command(cmd)
        return _blocker_prompt(term)
    return _confirm_apply(term)
