from __future__ import annotations

import select
import shutil
import sys
import termios
import tty
from pathlib import Path
from typing import Sequence, TextIO

from .apply import apply_plan
from .dependencies import ensure_dependencies
from .doctor import run_doctor
from .plan import build_install_plan
from .shell import register_shell_command
from .verify import verify_install
from .wizard_models import (
    ASCII_GLYPHS, BACK, CANCEL, COLOR_MODES, GLYPH_MODES, PLATFORM_LABELS,
    SHORTCUT_FOOTER, STYLE_CODES, UNICODE_GLYPHS, WELCOME_BANNER, Choice,
    ChoiceInput, TerminalWizard, WizardState, _validate_mode,
    open_tty as _open_tty_impl,
)
import _localsetup.core.wizard_apply as _apply_mod
import _localsetup.core.wizard_catalog as _catalog_mod
import _localsetup.core.wizard_selection as _selection_mod
import _localsetup.core.wizard_steps as _steps_mod

_SELECTION_CAN_USE_CHECKBOX_KEYS = _selection_mod._can_use_checkbox_keys


def _sync_modules() -> None:
    _selection_mod.select = select
    _selection_mod.termios = termios
    _selection_mod.tty = tty
    if "_FACADE_CAN_USE_CHECKBOX_KEYS" in globals() and _can_use_checkbox_keys is not _FACADE_CAN_USE_CHECKBOX_KEYS:
        _selection_mod._can_use_checkbox_keys = _can_use_checkbox_keys
    else:
        _selection_mod._can_use_checkbox_keys = _SELECTION_CAN_USE_CHECKBOX_KEYS
    _steps_mod.build_install_plan = build_install_plan
    _steps_mod.run_doctor = run_doctor
    _apply_mod.build_install_plan = build_install_plan
    _apply_mod.ensure_dependencies = ensure_dependencies
    _apply_mod.apply_plan = apply_plan
    _apply_mod.register_shell_command = register_shell_command
    _apply_mod.verify_install = verify_install


def open_tty(*, color_mode: str = "auto", glyph_mode: str = "auto") -> TerminalWizard:
    return _open_tty_impl(color_mode=color_mode, glyph_mode=glyph_mode)

def _choice_from_input(*args, **kwargs):
    _sync_modules()
    return _selection_mod._choice_from_input(*args, **kwargs)

def _choice_list(*args, **kwargs):
    _sync_modules()
    return _selection_mod._choice_list(*args, **kwargs)

def _render_step_context(*args, **kwargs):
    _sync_modules()
    return _selection_mod._render_step_context(*args, **kwargs)

def _render_choices(*args, **kwargs):
    _sync_modules()
    return _selection_mod._render_choices(*args, **kwargs)

def _print_step_help(*args, **kwargs):
    _sync_modules()
    return _selection_mod._print_step_help(*args, **kwargs)

def _toggle_details(*args, **kwargs):
    _sync_modules()
    return _selection_mod._toggle_details(*args, **kwargs)

def _choice_footer(*args, **kwargs):
    _sync_modules()
    return _selection_mod._choice_footer(*args, **kwargs)

def _continue_footer(*args, **kwargs):
    _sync_modules()
    return _selection_mod._continue_footer(*args, **kwargs)

def _continue_prompt(*args, **kwargs):
    _sync_modules()
    return _selection_mod._continue_prompt(*args, **kwargs)

def _confirm_apply(*args, **kwargs):
    _sync_modules()
    return _selection_mod._confirm_apply(*args, **kwargs)

def _blocker_prompt(*args, **kwargs):
    _sync_modules()
    return _selection_mod._blocker_prompt(*args, **kwargs)

def _target_directory_prompt(*args, **kwargs):
    _sync_modules()
    return _selection_mod._target_directory_prompt(*args, **kwargs)

def choose_one(*args, **kwargs):
    _sync_modules()
    return _selection_mod.choose_one(*args, **kwargs)

def choose_many(*args, **kwargs):
    _sync_modules()
    return _selection_mod.choose_many(*args, **kwargs)

def _can_use_checkbox_keys(*args, **kwargs):
    _sync_modules()
    return _selection_mod._can_use_checkbox_keys(*args, **kwargs)

_FACADE_CAN_USE_CHECKBOX_KEYS = _can_use_checkbox_keys

def _read_key(*args, **kwargs):
    _sync_modules()
    return _selection_mod._read_key(*args, **kwargs)

def _read_escape_sequence(*args, **kwargs):
    _sync_modules()
    return _selection_mod._read_escape_sequence(*args, **kwargs)

def _escape_sequence_is_complete(*args, **kwargs):
    _sync_modules()
    return _selection_mod._escape_sequence_is_complete(*args, **kwargs)

def _render_checkbox(*args, **kwargs):
    _sync_modules()
    return _selection_mod._render_checkbox(*args, **kwargs)

def choose_many_checkbox(*args, **kwargs):
    _sync_modules()
    return _selection_mod.choose_many_checkbox(*args, **kwargs)

def _platform_choices(*args, **kwargs):
    return _catalog_mod._platform_choices(*args, **kwargs)

def _pack_choices(*args, **kwargs):
    return _catalog_mod._pack_choices(*args, **kwargs)

def _skill_class_choices(*args, **kwargs):
    return _catalog_mod._skill_class_choices(*args, **kwargs)

def _skill_tag_choices(*args, **kwargs):
    return _catalog_mod._skill_tag_choices(*args, **kwargs)

def _skill_choices(*args, **kwargs):
    return _catalog_mod._skill_choices(*args, **kwargs)

def _attach_choices(*args, **kwargs):
    return _catalog_mod._attach_choices(*args, **kwargs)

def _dependency_choices(*args, **kwargs):
    return _catalog_mod._dependency_choices(*args, **kwargs)

def _global_root(*args, **kwargs):
    return _catalog_mod._global_root(*args, **kwargs)

def _registry_path(*args, **kwargs):
    return _catalog_mod._registry_path(*args, **kwargs)

def _source_identity(*args, **kwargs):
    return _catalog_mod._source_identity(*args, **kwargs)

def _selector_payload(*args, **kwargs):
    return _catalog_mod._selector_payload(*args, **kwargs)

def _load_prior_defaults(*args, **kwargs):
    return _catalog_mod._load_prior_defaults(*args, **kwargs)

def _action_summary(*args, **kwargs):
    return _catalog_mod._action_summary(*args, **kwargs)

def _detach_prior_adapters(*args, **kwargs):
    return _catalog_mod._detach_prior_adapters(*args, **kwargs)

def _show_welcome(*args, **kwargs):
    _sync_modules()
    return _steps_mod._show_welcome(*args, **kwargs)

def _source_step(*args, **kwargs):
    _sync_modules()
    return _steps_mod._source_step(*args, **kwargs)

def _mode_step(*args, **kwargs):
    _sync_modules()
    return _steps_mod._mode_step(*args, **kwargs)

def _platform_step(*args, **kwargs):
    _sync_modules()
    return _steps_mod._platform_step(*args, **kwargs)

def _pack_step(*args, **kwargs):
    _sync_modules()
    return _steps_mod._pack_step(*args, **kwargs)

def _skill_group_step(*args, **kwargs):
    _sync_modules()
    return _steps_mod._skill_group_step(*args, **kwargs)

def _skill_individual_step(*args, **kwargs):
    _sync_modules()
    return _steps_mod._skill_individual_step(*args, **kwargs)

def _options_step(*args, **kwargs):
    _sync_modules()
    return _steps_mod._options_step(*args, **kwargs)

def _review_step(*args, **kwargs):
    _sync_modules()
    return _steps_mod._review_step(*args, **kwargs)

def _apply_and_show_result(*args, **kwargs):
    _sync_modules()
    return _apply_mod._apply_and_show_result(*args, **kwargs)

def _write_interrupted_message(*args, **kwargs):
    _sync_modules()
    return _apply_mod._write_interrupted_message(*args, **kwargs)

def run_wizard(
    *,
    repo_root: Path,
    home: Path,
    caller_directory: Path | None = None,
    target_directory: Path | None = None,
    target_directory_is_explicit: bool = False,
    platforms: list[str] | None = None,
    packs: list[str] | None = None,
    preset: str | None = None,
    skills: list[str] | None = None,
    workflows: list[str] | None = None,
    skill_classes: list[str] | None = None,
    skill_tags: list[str] | None = None,
    exclude_skills: list[str] | None = None,
    global_packs: list[str] | None = None,
    global_preset: str | None = None,
    global_skills: list[str] | None = None,
    global_workflows: list[str] | None = None,
    global_skill_classes: list[str] | None = None,
    global_skill_tags: list[str] | None = None,
    global_exclude_skills: list[str] | None = None,
    repo_packs: list[str] | None = None,
    repo_preset: str | None = None,
    repo_skills: list[str] | None = None,
    repo_workflows: list[str] | None = None,
    repo_skill_classes: list[str] | None = None,
    repo_skill_tags: list[str] | None = None,
    repo_exclude_skills: list[str] | None = None,
    attach_mode: str = "symlink",
    dependency_mode: str = "prompt-only",
    register_shell: bool = True,
    terminal: TerminalWizard | None = None,
    color_mode: str = "auto",
    glyph_mode: str = "auto",
) -> int:
    term = terminal or open_tty(color_mode=color_mode, glyph_mode=glyph_mode)
    state = WizardState(
        repo_root=repo_root.resolve(),
        home=home.expanduser().resolve(),
        caller_directory=(caller_directory or Path.cwd()).expanduser().resolve(),
        target_directory=target_directory.expanduser().resolve() if target_directory else None,
        target_directory_is_explicit=target_directory_is_explicit,
        platforms=platforms,
        platforms_were_provided=platforms is not None,
        packs=packs,
        preset=preset,
        skills=skills,
        workflows=workflows,
        skill_classes=skill_classes,
        skill_tags=skill_tags,
        exclude_skills=exclude_skills,
        global_packs=global_packs,
        global_preset=global_preset,
        global_skills=global_skills,
        global_workflows=global_workflows,
        global_skill_classes=global_skill_classes,
        global_skill_tags=global_skill_tags,
        global_exclude_skills=global_exclude_skills,
        repo_packs=repo_packs,
        repo_preset=repo_preset,
        repo_skills=repo_skills,
        repo_workflows=repo_workflows,
        repo_skill_classes=repo_skill_classes,
        repo_skill_tags=repo_skill_tags,
        repo_exclude_skills=repo_exclude_skills,
        attach_mode=attach_mode,
        dependency_mode=dependency_mode,
        register_shell=register_shell,
    )
    _load_prior_defaults(state)
    state.detail_mode = term.detail_mode
    term.clear_screen()
    steps = [
        _show_welcome,
        _pack_step,
        _mode_step,
        _platform_step,
        _review_step,
    ]
    index = 0
    apply_started = False
    try:
        while index < len(steps):
            term.current_progress = f"Step {index + 1}/{len(steps)}"
            result = steps[index](term, state)
            state.detail_mode = term.detail_mode
            if result == CANCEL:
                term.write("Install canceled. No changes were applied.")
                return 130
            if result == BACK:
                index = max(0, index - 1)
                continue
            if result == "apply":
                apply_started = True
                term.current_progress = None
                return _apply_and_show_result(term, state)
            index += 1
        term.current_progress = None
        return 1
    except KeyboardInterrupt:
        _write_interrupted_message(term, apply_started=apply_started)
        return 130
    finally:
        if terminal is None:
            term.close()
