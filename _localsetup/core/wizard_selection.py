"""Wizard selection and prompt controls."""

from __future__ import annotations

import select
import termios
import tty
from typing import Sequence

from .wizard_models import BACK, CANCEL, SHORTCUT_FOOTER, Choice, ChoiceInput, TerminalWizard

def _choice_from_input(choice: ChoiceInput) -> Choice:
    if isinstance(choice, Choice):
        return choice
    value, label = choice
    return Choice(
        value=value,
        label=label,
        summary=label,
        effect=f"Selects {label}.",
        best_for=f"Choose when {label} is the option you want.",
        tradeoff="No additional tradeoff is defined for this option.",
    )

def _choice_list(choices: Sequence[ChoiceInput]) -> list[Choice]:
    return [_choice_from_input(choice) for choice in choices]

def _render_step_context(
    term: TerminalWizard,
    *,
    decides: str | None,
    suggested: Choice | None,
    suggested_reason: str | None,
) -> None:
    if decides:
        term.detail_line(f"Decides: {decides}")
    if suggested:
        reason = suggested_reason or suggested.best_for
        term.detail_line(f"{term.glyph('suggested')} Suggested: {suggested.label} - {reason}", style="suggested")
    if decides or suggested:
        term.write("")

def _render_choices(term: TerminalWizard, choices: list[Choice], *, default_values: set[str]) -> None:
    for i, choice in enumerate(choices, start=1):
        term.choice_row(i, choice, suggested=choice.value in default_values)

def _print_step_help(term: TerminalWizard, *, help_text: str | None, allow_many: bool) -> None:
    if help_text:
        term.write(help_text)
    elif allow_many:
        term.write("Enter one number, several comma-separated numbers, a value, or a label.")
    else:
        term.write("Enter a number, value, or label from the list.")
    term.write("Use d to switch between detailed and compact explanations.")

def _toggle_details(term: TerminalWizard) -> None:
    term.detail_mode = not term.detail_mode
    mode = "detailed" if term.detail_mode else "compact"
    term.write(f"Detail mode: {mode}.")

def _choice_footer(term: TerminalWizard) -> str:
    return term.footer()

def _continue_footer(term: TerminalWizard) -> str:
    return term.footer()

def _continue_prompt(term: TerminalWizard, prompt: str, *, help_text: str, detail_text: str | None = None) -> str:
    while True:
        answer = term.prompt(prompt, default="continue", footer=_continue_footer(term))
        if answer in {BACK, CANCEL}:
            return answer
        lowered = answer.lower()
        if lowered == "?":
            term.write(help_text)
            continue
        if lowered in {"d", "details"}:
            _toggle_details(term)
            if term.detail_mode and detail_text:
                term.write(detail_text)
            continue
        return "continue"

def _confirm_apply(term: TerminalWizard) -> str:
    while True:
        answer = term.prompt(
            "Apply this install? Type yes to continue",
            default="no",
            footer=SHORTCUT_FOOTER,
        )
        if answer in {BACK, CANCEL}:
            return answer
        lowered = answer.lower()
        if lowered == "?":
            term.write("Type yes only after the review matches what you want. Type b to change options or q to cancel.")
            continue
        if lowered in {"d", "details"}:
            _toggle_details(term)
            term.write(
                "The apply step writes the managed library, selected skills/workflows, "
                "optional adapter paths, shell command, and lockfile."
            )
            continue
        return "apply" if lowered == "yes" else BACK

def _blocker_prompt(term: TerminalWizard) -> str:
    while True:
        answer = term.prompt(
            "Enter b to change options or q to cancel",
            default="b",
            footer=SHORTCUT_FOOTER,
        )
        if answer in {BACK, CANCEL}:
            return answer
        lowered = answer.lower()
        if lowered == "?":
            term.write("Blockers must be fixed before apply. Use the diagnostic command above for a detailed report.")
            continue
        if lowered in {"d", "details"}:
            _toggle_details(term)
            term.write("A blocker means the installer detected a condition that could make the install fail or unusable.")
            continue
        return BACK

def _target_directory_prompt(term: TerminalWizard) -> str:
    while True:
        answer = term.prompt("Target directory", footer=SHORTCUT_FOOTER)
        if answer in {BACK, CANCEL}:
            return answer
        lowered = answer.lower()
        if lowered == "?":
            term.write("Enter the repo directory to prepare with agent adapter paths.")
            continue
        if lowered in {"d", "details"}:
            _toggle_details(term)
            term.write("The target directory receives adapter paths and a Localsetup lockfile after the review is applied.")
            continue
        return answer

def choose_one(
    term: TerminalWizard,
    prompt: str,
    choices: Sequence[ChoiceInput],
    *,
    default: str,
    decides: str | None = None,
    suggested_reason: str | None = None,
    help_text: str | None = None,
) -> str:
    normalized = _choice_list(choices)
    valid = {str(i): choice.value for i, choice in enumerate(normalized, start=1)}
    labels = {choice.value: choice.label for choice in normalized}
    default_number = next((num for num, value in valid.items() if value == default), "1")
    suggested = next((choice for choice in normalized if choice.value == default), normalized[0] if normalized else None)
    while True:
        _render_step_context(term, decides=decides, suggested=suggested, suggested_reason=suggested_reason)
        _render_choices(term, normalized, default_values={default})
        answer = term.prompt(prompt, default=default_number, footer=_choice_footer(term))
        if answer in {BACK, CANCEL}:
            return answer
        lowered = answer.lower()
        if lowered == "?":
            _print_step_help(term, help_text=help_text, allow_many=False)
            continue
        if lowered in {"d", "details"}:
            _toggle_details(term)
            continue
        if answer in valid:
            return valid[answer]
        for value, label in labels.items():
            if lowered in {value.lower(), label.lower()}:
                return value
        term.write("Choose one of the listed numbers, enter d for detail mode, ? for help, b to go back, or q to cancel.")

def choose_many(
    term: TerminalWizard,
    prompt: str,
    choices: Sequence[ChoiceInput],
    *,
    default: list[str],
    allow_none: bool = True,
    decides: str | None = None,
    suggested_reason: str | None = None,
    help_text: str | None = None,
) -> list[str] | str:
    normalized = _choice_list(choices)
    valid = {str(i): choice.value for i, choice in enumerate(normalized, start=1)}
    labels = {choice.value: choice.label for choice in normalized}
    default_numbers = [num for num, value in valid.items() if value in default]
    default_text = ",".join(default_numbers) if default_numbers else "none"
    suggested = next((choice for choice in normalized if choice.value in default), normalized[0] if normalized else None)
    while True:
        _render_step_context(term, decides=decides, suggested=suggested, suggested_reason=suggested_reason)
        _render_choices(term, normalized, default_values=set(default))
        if allow_none:
            term.write("  0. None")
        answer = term.prompt(prompt, default=default_text, footer=_choice_footer(term))
        if answer in {BACK, CANCEL}:
            return answer
        lowered = answer.lower()
        if lowered == "?":
            _print_step_help(term, help_text=help_text, allow_many=True)
            continue
        if lowered in {"d", "details"}:
            _toggle_details(term)
            continue
        if allow_none and lowered in {"none", "0"}:
            return []
        exact_value = next(
            (choice_value for choice_value, label in labels.items() if lowered in {choice_value.lower(), label.lower()}),
            None,
        )
        if exact_value is not None:
            return [exact_value]
        parts = [part.strip() for part in answer.replace(" ", ",").split(",") if part.strip()]
        selected: list[str] = []
        bad: list[str] = []
        for part in parts:
            value = valid.get(part)
            if value is None:
                value = next(
                    (choice_value for choice_value, label in labels.items() if part.lower() in {choice_value.lower(), label.lower()}),
                    None,
                )
            if value is None:
                bad.append(part)
            elif value not in selected:
                selected.append(value)
        if not bad and (selected or allow_none):
            return selected
        term.write("Choose comma-separated numbers from the list, enter d for detail mode, ? for help, b to go back, or q to cancel.")

def _can_use_checkbox_keys(term: TerminalWizard) -> bool:
    return (
        not term.force_line_mode
        and TerminalWizard._is_tty(term.input)
        and TerminalWizard._is_tty(term.output)
        and hasattr(term.input, "fileno")
        and hasattr(term.output, "fileno")
    )

def _read_key(term: TerminalWizard) -> str:
    char = term.input.read(1)
    if char == "\x03":
        return "ctrl-c"
    if char == "\x1b":
        sequence = _read_escape_sequence(term)
        if sequence.startswith("[") and sequence.endswith("A"):
            return "up"
        if sequence.startswith("[") and sequence.endswith("B"):
            return "down"
        if sequence == "OA":
            return "up"
        if sequence == "OB":
            return "down"
        return "unknown"
    if char in {"\r", "\n"}:
        return "enter"
    if char == " ":
        return "space"
    if char == "":
        return "unknown"
    return char.lower()

def _read_escape_sequence(term: TerminalWizard, *, max_chars: int = 12) -> str:
    try:
        fd = term.input.fileno()
    except (AttributeError, OSError):
        return ""
    sequence = ""
    for _ in range(max_chars):
        ready, _, _ = select.select([fd], [], [], 0.05)
        if not ready:
            break
        next_char = term.input.read(1)
        if not next_char:
            break
        sequence += next_char
        if _escape_sequence_is_complete(sequence):
            break
    return sequence

def _escape_sequence_is_complete(sequence: str) -> bool:
    if sequence.startswith("["):
        return len(sequence) >= 2 and "@" <= sequence[-1] <= "~"
    if sequence.startswith("O"):
        return len(sequence) >= 2
    return bool(sequence)

def _render_checkbox(
    term: TerminalWizard,
    prompt: str,
    choices: list[Choice],
    *,
    selected: set[str],
    cursor: int,
    decides: str | None,
    suggested: Choice | None,
    suggested_reason: str | None,
) -> None:
    term.output.write("\033[H\033[J")
    term.title(prompt)
    _render_step_context(term, decides=decides, suggested=suggested, suggested_reason=suggested_reason)
    for index, choice in enumerate(choices):
        pointer = ">" if index == cursor else " "
        marker = "[x]" if choice.value in selected else "[ ]"
        term.write(f"{pointer} {marker} {choice.label}")
        term.detail_line(choice.summary, indent="      ", style="muted")
        if term.detail_mode and index == cursor:
            term.detail_line(f"Does: {choice.effect}", indent="      ")
            term.detail_line(f"Choose when: {choice.best_for}", indent="      ")
            term.detail_line(f"Tradeoff: {choice.tradeoff}", indent="      ")
            if choice.caution:
                term.detail_line(f"Caution: {choice.caution}", indent="      ", style="warning")
    term.write(term.token("Space toggle | Enter accept | arrows/j/k move | a all | n none | d details | b back | q quit | ? help", "shortcut"))
    term.output.flush()

def choose_many_checkbox(
    term: TerminalWizard,
    prompt: str,
    choices: Sequence[ChoiceInput],
    *,
    default: list[str],
    allow_none: bool = True,
    decides: str | None = None,
    suggested_reason: str | None = None,
    help_text: str | None = None,
) -> list[str] | str:
    if not _can_use_checkbox_keys(term):
        return choose_many(
            term,
            prompt,
            choices,
            default=default,
            allow_none=allow_none,
            decides=decides,
            suggested_reason=suggested_reason,
            help_text=help_text,
        )
    normalized = _choice_list(choices)
    selected = {choice.value for choice in normalized if choice.value in set(default)}
    cursor = 0
    suggested = next((choice for choice in normalized if choice.value in selected), normalized[0] if normalized else None)
    old_settings = termios.tcgetattr(term.input.fileno())
    try:
        tty.setcbreak(term.input.fileno())
        while True:
            _render_checkbox(
                term,
                prompt,
                normalized,
                selected=selected,
                cursor=cursor,
                decides=decides,
                suggested=suggested,
                suggested_reason=suggested_reason,
            )
            key = _read_key(term)
            if key in {"q", "ctrl-c"}:
                return CANCEL
            if key == "b":
                return BACK
            if key == "?":
                term.write(help_text or "Use Space to toggle the highlighted item, then Enter to accept.")
                continue
            if key == "d":
                _toggle_details(term)
                continue
            if key in {"up", "k"}:
                cursor = max(0, cursor - 1)
                continue
            if key in {"down", "j"}:
                cursor = min(len(normalized) - 1, cursor + 1)
                continue
            if key == "a":
                selected = {choice.value for choice in normalized}
                continue
            if key == "n":
                selected = set()
                continue
            if key == "space" and normalized:
                value = normalized[cursor].value
                if value in selected:
                    selected.remove(value)
                else:
                    selected.add(value)
                continue
            if key == "enter" and (selected or allow_none):
                return [choice.value for choice in normalized if choice.value in selected]
    finally:
        termios.tcsetattr(term.input.fileno(), termios.TCSADRAIN, old_settings)
