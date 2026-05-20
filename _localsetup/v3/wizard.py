from __future__ import annotations

from dataclasses import dataclass
import locale
import os
import select
import shutil
import sys
import termios
import textwrap
import tty
from pathlib import Path
from typing import Sequence, TextIO

from .adapters import adapter_path_state, legacy_global_roots
from .apply import apply_plan
from .dependencies import ensure_dependencies
from .doctor import run_doctor
from .lockfile import load_json
from .manifests import load_pack_config, load_platforms
from .paths import expand_user_path, legacy_target_lockfile_path
from .plan import build_install_plan
from .registry import load_registry
from .selection import recommended_packs_for_target, resolve_package_selection
from .shell import register_shell_command
from .skills import load_skill_catalog
from .verify import verify_install


BACK = "__back__"
CANCEL = "__cancel__"

PLATFORM_LABELS = {
    "codex": "Codex",
    "cursor": "Cursor",
    "claude-code": "Claude Code",
    "kilo": "Kilo",
    "opencode": "OpenCode",
    "openclaw": "OpenClaw",
}

SHORTCUT_FOOTER = "Enter number(s) | d details | b back | q quit | ? help"
COLOR_MODES = {"auto", "always", "never"}
GLYPH_MODES = {"auto", "ascii", "unicode"}

STYLE_CODES = {
    "heading": "1;36",
    "rule": "36",
    "muted": "2",
    "shortcut": "1;37",
    "choice_number": "1;36",
    "suggested": "1;32",
    "path": "36",
    "command": "1;37",
    "success": "32",
    "warning": "33",
    "error": "31",
    "blocker": "31",
    "planned": "36",
}

ASCII_GLYPHS = {
    "ok": "[OK]",
    "warn": "[WARN]",
    "fail": "[FAIL]",
    "info": "[INFO]",
    "plan": "[PLAN]",
    "suggested": "[SUGGESTED]",
}

UNICODE_GLYPHS = {
    "ok": "[OK] ✓",
    "warn": "[WARN] !",
    "fail": "[FAIL] ✕",
    "info": "[INFO] •",
    "plan": "[PLAN] →",
    "suggested": "[SUGGESTED] ★",
}

WELCOME_BANNER = r""" _      ___   ____    _    _     ____  _____ _____ _   _ ____
| |    / _ \ / ___|  / \  | |   / ___|| ____|_   _| | | |  _ \
| |   | | | | |     / _ \ | |   \___ \|  _|   | | | | | | |_) |
| |___| |_| | |___ / ___ \| |___ ___) | |___  | | | |_| |  __/
|_____|\___/ \____/_/   \_\_____|____/|_____| |_|  \___/|_|
                         v3 installer"""


@dataclass
class Choice:
    value: str
    label: str
    summary: str
    effect: str
    best_for: str
    tradeoff: str
    caution: str | None = None


ChoiceInput = Choice | tuple[str, str]


@dataclass
class WizardState:
    repo_root: Path
    home: Path
    caller_directory: Path
    target_directory: Path | None = None
    target_directory_is_explicit: bool = False
    prior_target_directory: Path | None = None
    prior_adapter_targets: list[dict] | None = None
    detach_repo_setup: bool = False
    platforms: list[str] | None = None
    platforms_were_provided: bool = False
    packs: list[str] | None = None
    preset: str | None = None
    skills: list[str] | None = None
    skill_classes: list[str] | None = None
    skill_tags: list[str] | None = None
    exclude_skills: list[str] | None = None
    global_packs: list[str] | None = None
    global_preset: str | None = None
    global_skills: list[str] | None = None
    global_skill_classes: list[str] | None = None
    global_skill_tags: list[str] | None = None
    global_exclude_skills: list[str] | None = None
    repo_packs: list[str] | None = None
    repo_preset: str | None = None
    repo_skills: list[str] | None = None
    repo_skill_classes: list[str] | None = None
    repo_skill_tags: list[str] | None = None
    repo_exclude_skills: list[str] | None = None
    attach_mode: str = "symlink"
    dependency_mode: str = "prompt-only"
    register_shell: bool = True
    detail_mode: bool = True


class TerminalWizard:
    def __init__(
        self,
        input_stream: TextIO,
        output_stream: TextIO,
        *,
        color: bool | None = None,
        color_mode: str = "auto",
        glyph_mode: str | None = None,
    ) -> None:
        self.input = input_stream
        self.output = output_stream
        if color is not None:
            color_mode = "always" if color else "never"
            if color is False and glyph_mode is None:
                glyph_mode = "ascii"
        if glyph_mode is None:
            glyph_mode = "auto"
        self.color_mode = _validate_mode(color_mode, COLOR_MODES, "color")
        self.glyph_mode = _validate_mode(glyph_mode, GLYPH_MODES, "glyphs")
        self.color = self._resolve_color(output_stream, self.color_mode)
        self.unicode_glyphs = self._resolve_glyphs(output_stream, self.glyph_mode)
        self.detail_mode = os.environ.get("LOCALSETUP_WIZARD_DETAIL", "").lower() not in {"compact", "off", "0"}
        self.force_line_mode = os.environ.get("LOCALSETUP_WIZARD_SELECTION_MODE", "").lower() in {
            "line",
            "plain",
            "scripted",
        }
        self.current_progress: str | None = None

    @staticmethod
    def _supports_color(stream: TextIO) -> bool:
        return TerminalWizard._resolve_color(stream, "auto")

    @staticmethod
    def _is_tty(stream: TextIO) -> bool:
        return hasattr(stream, "isatty") and stream.isatty()

    @staticmethod
    def _resolve_color(stream: TextIO, mode: str) -> bool:
        if mode == "always":
            return True
        if mode == "never":
            return False
        if os.environ.get("NO_COLOR") is not None:
            return False
        if os.environ.get("FORCE_COLOR") is not None:
            return True
        if os.environ.get("TERM", "").lower() in {"dumb", "unknown"}:
            return False
        return TerminalWizard._is_tty(stream)

    @staticmethod
    def _resolve_glyphs(stream: TextIO, mode: str) -> bool:
        if mode == "unicode":
            return True
        if mode == "ascii":
            return False
        if not TerminalWizard._is_tty(stream):
            return False
        if os.environ.get("TERM", "").lower() in {"dumb", "unknown"}:
            return False
        encoding = getattr(stream, "encoding", None) or locale.getpreferredencoding(False)
        return "utf" in encoding.lower()

    def close(self) -> None:
        for stream in {self.input, self.output}:
            if stream not in {sys.stdin, sys.stdout, sys.stderr}:
                try:
                    stream.close()
                except OSError:
                    pass

    def style(self, text: str, code: str) -> str:
        if not self.color:
            return text
        return f"\033[{code}m{text}\033[0m"

    def token(self, text: str, token: str) -> str:
        return self.style(text, STYLE_CODES.get(token, "0"))

    def glyph(self, name: str) -> str:
        glyphs = UNICODE_GLYPHS if self.unicode_glyphs else ASCII_GLYPHS
        return glyphs.get(name, f"[{name.upper()}]")

    def width(self) -> int:
        try:
            return shutil.get_terminal_size((88, 24)).columns
        except OSError:
            return 88

    def title(self, text: str) -> None:
        self.step_header(text, progress=self.current_progress)

    def step_header(self, text: str, *, progress: str | None = None) -> None:
        heading = f"{progress} - {text}" if progress else text
        self.write("")
        self.write(self.token(heading, "heading"))
        self.write(self.token("-" * len(heading), "rule"))

    def detail_line(self, text: str, *, indent: str = "", style: str = "muted") -> None:
        width = max(40, self.width())
        for line in textwrap.wrap(text, width=width, initial_indent=indent, subsequent_indent=indent):
            self.write(self.token(line, style))

    def key_value_block(self, rows: Sequence[tuple[str, str]], *, indent: str = "") -> None:
        label_width = max((len(label) for label, _ in rows), default=0)
        width = max(40, self.width())
        for label, value in rows:
            prefix = f"{indent}{label + ':':<{label_width + 1}} "
            wrapped = textwrap.wrap(str(value), width=max(20, width - len(prefix)))
            if not wrapped:
                self.write(prefix.rstrip())
                continue
            self.write(prefix + wrapped[0])
            continuation = " " * len(prefix)
            for line in wrapped[1:]:
                self.write(continuation + line)

    def choice_row(self, index: int, choice: Choice, *, suggested: bool = False) -> None:
        marker = f" {self.token(self.glyph('suggested'), 'suggested')}" if suggested else ""
        number = self.token(f"{index}.", "choice_number")
        self.write(f"  {number} {choice.label}{marker}")
        self.detail_line(choice.summary, indent="     ", style="muted")
        if self.detail_mode:
            self.detail_line(f"Does: {choice.effect}", indent="     ")
            self.detail_line(f"Choose when: {choice.best_for}", indent="     ")
            self.detail_line(f"Tradeoff: {choice.tradeoff}", indent="     ")
            if choice.caution:
                self.detail_line(f"Caution: {choice.caution}", indent="     ", style="warning")

    def status_line(self, kind: str, text: str) -> None:
        style = {"ok": "success", "warn": "warning", "fail": "error", "info": "muted", "plan": "planned"}.get(kind, "muted")
        self.write(f"{self.token(self.glyph(kind), style)} {text}")

    def action_list(self, lines: Sequence[str]) -> None:
        for line in lines:
            self.detail_line(f"{self.glyph('plan')} {line}", indent="  ", style="planned")

    def diagnostic_command(self, command: Sequence[str] | str) -> None:
        command_text = command if isinstance(command, str) else " ".join(command)
        self.write("Diagnostic command:")
        self.detail_line(command_text, indent="  ", style="command")

    def footer(self) -> str:
        return self.token(SHORTCUT_FOOTER, "shortcut")

    def clear_screen(self) -> None:
        if not (hasattr(self.output, "isatty") and self.output.isatty()):
            return
        if os.environ.get("TERM") == "dumb":
            return
        self.output.write("\033[2J\033[3J\033[H")
        self.output.flush()

    def banner(self, text: str) -> None:
        self.write(self.token(text, "heading"))

    def write(self, text: str = "") -> None:
        print(text, file=self.output)

    def prompt(self, prompt: str, *, default: str | None = None, footer: str | None = None) -> str:
        suffix = f" [{default}]" if default else ""
        while True:
            if footer:
                self.write(footer)
            self.output.write(f"{prompt}{suffix}: ")
            self.output.flush()
            try:
                line = self.input.readline()
            except KeyboardInterrupt:
                self.write("")
                return CANCEL
            if line == "":
                return CANCEL
            value = line.strip()
            if not value and default is not None:
                return default
            lower = value.lower()
            if lower in {"q", "quit", "cancel", "c"}:
                return CANCEL
            if lower in {"b", "back"}:
                return BACK
            return value


def _validate_mode(value: str, choices: set[str], name: str) -> str:
    if value not in choices:
        raise ValueError(f"invalid {name} mode: {value}")
    return value


def open_tty(*, color_mode: str = "auto", glyph_mode: str = "auto") -> TerminalWizard:
    try:
        tty_in = open("/dev/tty", "r", encoding="utf-8", errors="replace")
        tty_out = open("/dev/tty", "w", encoding="utf-8", errors="replace")
    except OSError as exc:
        raise RuntimeError(
            "interactive installer requires a terminal. Run with a TTY, or use --non-interactive --yes for automation."
        ) from exc
    return TerminalWizard(tty_in, tty_out, color_mode=color_mode, glyph_mode=glyph_mode)


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


def _platform_choices(repo_root: Path) -> list[Choice]:
    choices: list[Choice] = []
    for platform in load_platforms(repo_root):
        label = PLATFORM_LABELS.get(platform.platform_id, platform.platform_id)
        repo_paths = ", ".join(platform.repo_paths) if platform.repo_paths else "no repo adapter path"
        global_paths = ", ".join(platform.global_paths) if platform.global_paths else "no global adapter path"
        choices.append(
            Choice(
                value=platform.platform_id,
                label=label,
                summary=f"Writes adapter path {repo_paths}.",
                effect=f"Connects this repo to Localsetup skills for {label} through {repo_paths}.",
                best_for=f"You use {label} in this repository and want its agent skill picker to see Localsetup.",
                tradeoff=f"Creates or updates repo-local adapter path(s); global fallback is {global_paths}.",
            )
        )
    return choices


def _pack_choices(repo_root: Path) -> list[Choice]:
    pack = load_pack_config(repo_root)
    names = list(dict.fromkeys(["core", *pack.optional_packs, *pack.packs.keys()]))
    metadata = {
        "core": (
            "Everyday Localsetup context, safety, task matching, and test workflow basics.",
            "Installs the normal starter set for interactive agent work.",
            "You want the suggested default for regular use.",
            "Keeps the install compact; specialized ops, publishing, and integrations stay out until selected.",
        ),
        "bootstrap": (
            "Agent-team startup, repo audit, safety, docs, git, and testing pack.",
            "Adds the skills most useful when bringing a repo under agent-team workflow control.",
            "You are preparing a repo for structured controller-led work or first-pass audits.",
            "Overlaps with core and dev, so it is a little broader than a minimalist install.",
        ),
        "dev": (
            "Code, docs, git, testing, markdown validation, and repo repair workflows.",
            "Adds developer-maintenance skills for day-to-day implementation and cleanup.",
            "You will edit, test, audit, or repair this repository with agents.",
            "Adds more repo-maintenance surface than a simple end-user setup needs.",
        ),
        "ops": (
            "Server, cron, Linux service, Ansible, patching, and baseline diagnostics workflows.",
            "Installs operational skills for maintaining machines and services.",
            "This repo manages infrastructure, servers, scheduled work, or service triage.",
            "Not needed for most app-only repositories.",
        ),
        "integrations": (
            "External systems and service connectors such as DNS, mail, secrets, MCP, NPM, and scraping.",
            "Adds skills that talk to outside services or local credential-backed systems.",
            "You expect agents to work with integrations after setup.",
            "Some workflows may require credentials or extra host tools before use.",
        ),
        "publishing": (
            "Release, public repo identity, PR review, GitHub publishing, and automatic versioning support.",
            "Installs skills for publishing and release hygiene.",
            "You plan to ship changes, prepare public docs, or manage release flow.",
            "Adds release-process opinions that are unnecessary for private scratch repos.",
        ),
        "harness": (
            "Opt-in autonomous harness capability for Codex heartbeat checks.",
            "Installs the heartbeat skill and workflow only; activation still requires explicit harness commands.",
            "You want a target repo to support scheduled heartbeat runs after a deliberate enable step.",
            "Does not create config, cron entries, or state during normal install.",
        ),
        "experimental": (
            "Advanced, less-conservative, or specialist workflows.",
            "Installs exploratory skills for orchestration, skill import/vetting, and higher-risk workflows.",
            "You know you need these advanced tools and accept extra review responsibility.",
            "Less conservative by design; review before relying on them in production workflows.",
        ),
    }
    out: list[Choice] = []
    for name in names:
        summary, effect, best_for, tradeoff = metadata.get(
            name,
            (
                f"Installs the {name} pack.",
                f"Adds skills and workflows listed under {name} in pack.yaml.",
                f"You need the {name} capability set.",
                "Review the pack contents if you are unsure.",
            ),
        )
        out.append(Choice(name, name, summary, effect, best_for, tradeoff))
    return out


def _skill_class_choices(repo_root: Path) -> list[Choice]:
    classes = sorted({skill.taxonomy_class for skill in load_skill_catalog(repo_root) if skill.taxonomy_class})
    return [
        Choice(
            value=name,
            label=name,
            summary=f"Adds all skills classified as {name}.",
            effect=f"Includes every shipped skill with taxonomy class {name}.",
            best_for=f"You want the {name} capability group without picking each skill.",
            tradeoff="May add skills outside the selected packs.",
        )
        for name in classes
    ]


def _skill_tag_choices(repo_root: Path) -> list[Choice]:
    tags = sorted({tag for skill in load_skill_catalog(repo_root) for tag in skill.tags})
    return [
        Choice(
            value=tag,
            label=tag,
            summary=f"Adds skills tagged {tag}.",
            effect=f"Includes shipped skills whose taxonomy tags include {tag}.",
            best_for=f"You need the {tag} capability regardless of pack.",
            tradeoff="Tags are additive; review individual skills on the next screen.",
        )
        for tag in tags
    ]


def _skill_choices(repo_root: Path) -> list[Choice]:
    return [
        Choice(
            value=skill.name,
            label=skill.name,
            summary=f"{skill.taxonomy_class}; packs: {', '.join(skill.packs) or 'none'}; tags: {', '.join(skill.tags) or 'none'}.",
            effect=skill.description,
            best_for=f"You want {skill.name} available in the selected install footprint.",
            tradeoff="Unselecting a workflow-required skill may be overridden by the workflow dependency.",
        )
        for skill in load_skill_catalog(repo_root)
    ]


def _attach_choices() -> list[Choice]:
    return [
        Choice(
            "symlink",
            "Symlink adapters",
            "Repo adapter paths point at the managed Localsetup library.",
            "Creates links such as `.codex/skills` so updates to the managed library are picked up immediately.",
            "You want the easiest update path and are comfortable with repo-local symlinks.",
            "The repo depends on the managed library path existing on this machine.",
        ),
        Choice(
            "portable",
            "Portable adapter copies",
            "Repo adapter paths get their own copied skill tree.",
            "Copies selected skills into adapter paths so the repo is more self-contained.",
            "You need fewer links to machine-global locations or plan to move the repo around.",
            "Updates require copying again, and the repo uses more disk space.",
        ),
    ]


def _dependency_choices() -> list[Choice]:
    return [
        Choice(
            "prompt-only",
            "Prompt only dependencies",
            "Reports missing dependencies without installing them.",
            "Leaves host dependency installation to you while still showing what is needed.",
            "You want the safest no-surprises install path.",
            "Some workflows may need manual dependency setup before they run.",
        ),
        Choice(
            "uv-sync",
            "Sync uv environment",
            "Prepares Localsetup's uv-managed Python environment.",
            "Creates or updates the source checkout .venv from pyproject.toml and uv.lock.",
            "You want the installer to prepare Python tooling now.",
            "Takes longer and requires uv plus access to the configured package index or cache.",
        ),
    ]


def _global_root(repo_root: Path, home: Path) -> Path:
    return expand_user_path(load_pack_config(repo_root).global_root, home)


def _registry_path(repo_root: Path, home: Path) -> Path:
    return expand_user_path(load_pack_config(repo_root).global_registry, home)


def _source_identity(repo_root: Path) -> str:
    import subprocess

    try:
        tag = subprocess.run(
            ["git", "-C", str(repo_root), "describe", "--tags", "--exact-match"],
            text=True,
            capture_output=True,
            check=False,
        )
        if tag.returncode == 0 and tag.stdout.strip():
            return tag.stdout.strip()
        commit = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
            text=True,
            capture_output=True,
            check=False,
        )
        if commit.returncode == 0 and commit.stdout.strip():
            return commit.stdout.strip()
    except OSError:
        pass
    return "unknown"


def _selector_payload(selectors: object) -> dict:
    return selectors if isinstance(selectors, dict) else {}


def _load_prior_defaults(state: WizardState) -> None:
    global_defaults_loaded = False
    registry_path = _registry_path(state.repo_root, state.home)
    if registry_path.exists():
        baseline = load_registry(registry_path).get("global_baseline", {})
        selectors = _selector_payload(baseline.get("selectors"))
        global_defaults_loaded = bool(baseline or selectors)
        prior_packs = list(selectors.get("packs") or baseline.get("packs") or [])
        if prior_packs and state.global_packs is None and state.packs is None:
            state.global_packs = prior_packs
        if state.global_preset is None and state.preset is None:
            state.global_preset = selectors.get("preset") or baseline.get("preset")
        if state.global_skills is None and state.skills is None:
            state.global_skills = list(selectors.get("skills") or [])
        if state.global_skill_classes is None and state.skill_classes is None:
            state.global_skill_classes = list(selectors.get("skill_classes") or [])
        if state.global_skill_tags is None and state.skill_tags is None:
            state.global_skill_tags = list(selectors.get("skill_tags") or [])
        if state.global_exclude_skills is None and state.exclude_skills is None:
            state.global_exclude_skills = list(selectors.get("exclude_skills") or [])

    candidate = state.target_directory or state.caller_directory
    lock_path = candidate / ".localsetup" / "lock.json"
    lock = load_json(lock_path)
    if not lock:
        lock = load_json(legacy_target_lockfile_path(candidate))
    if not lock:
        return
    state.prior_target_directory = candidate
    state.prior_adapter_targets = list(lock.get("adapter_targets") or [])
    if state.target_directory is None:
        target_value = lock.get("target_root")
        state.target_directory = Path(str(target_value)).expanduser().resolve() if target_value else candidate
        state.prior_target_directory = state.target_directory
    if state.platforms is None:
        state.platforms = list(lock.get("platforms") or [])
    if state.attach_mode == "symlink":
        state.attach_mode = str(lock.get("attach_mode") or state.attach_mode)
    if state.dependency_mode == "prompt-only" and lock.get("dependency_mode"):
        state.dependency_mode = str(lock["dependency_mode"])
    if not global_defaults_loaded:
        baseline_selectors = _selector_payload(lock.get("global_baseline_selectors") or lock.get("selectors"))
        prior_global_packs = list(
            baseline_selectors.get("packs")
            or lock.get("global_baseline_packs")
            or lock.get("packs")
            or []
        )
        if prior_global_packs and state.global_packs is None and state.packs is None:
            state.global_packs = prior_global_packs
        if state.global_preset is None and state.preset is None:
            state.global_preset = baseline_selectors.get("preset") or lock.get("global_baseline_preset") or lock.get("preset")
        if state.global_skills is None and state.skills is None:
            state.global_skills = list(baseline_selectors.get("skills") or lock.get("global_baseline_skills") or [])
        if state.global_skill_classes is None and state.skill_classes is None:
            state.global_skill_classes = list(baseline_selectors.get("skill_classes") or [])
        if state.global_skill_tags is None and state.skill_tags is None:
            state.global_skill_tags = list(baseline_selectors.get("skill_tags") or [])
        if state.global_exclude_skills is None and state.exclude_skills is None:
            state.global_exclude_skills = list(baseline_selectors.get("exclude_skills") or [])
    selectors = _selector_payload(lock.get("repo_selectors") or lock.get("selectors"))
    prior_repo_packs = list(selectors.get("packs") or lock.get("repo_packs") or [])
    if prior_repo_packs and state.repo_packs is None and state.packs is None:
        state.repo_packs = prior_repo_packs
    if state.repo_preset is None and state.preset is None:
        state.repo_preset = selectors.get("preset") or lock.get("repo_preset")
    if state.repo_skills is None and state.skills is None:
        state.repo_skills = list(selectors.get("skills") or [])
    if state.repo_skill_classes is None and state.skill_classes is None:
        state.repo_skill_classes = list(selectors.get("skill_classes") or [])
    if state.repo_skill_tags is None and state.skill_tags is None:
        state.repo_skill_tags = list(selectors.get("skill_tags") or [])
    if state.repo_exclude_skills is None and state.exclude_skills is None:
        state.repo_exclude_skills = list(selectors.get("exclude_skills") or [])


def _action_summary(actions: list[object]) -> list[str]:
    labels = {
        "ensure_dir": "Ensure managed skill library exists",
        "write_registry": "Write Localsetup registry",
        "install_skills": "Install selected skills",
        "install_workflows": "Install selected workflows",
        "attach_repo_path": "Attach selected adapter",
    }
    return [f"{labels.get(getattr(action, 'kind'), getattr(action, 'kind'))}: {getattr(action, 'path')}" for action in actions]


def _detach_prior_adapters(state: WizardState) -> list[str]:
    if not state.prior_adapter_targets:
        return []
    target_root = state.prior_target_directory or state.target_directory
    if target_root is None:
        return []
    resolved_target = target_root.resolve(strict=False)
    global_root = _global_root(state.repo_root, state.home)
    removed: list[str] = []
    for target in state.prior_adapter_targets:
        path_value = target.get("path") if isinstance(target, dict) else None
        if not path_value:
            continue
        path = Path(str(path_value))
        if not path.is_absolute() and state.prior_target_directory:
            path = state.prior_target_directory / path
        try:
            path.parent.resolve(strict=False).relative_to(resolved_target)
        except ValueError:
            continue
        adapter_state = adapter_path_state(path, global_root, known_global_roots=legacy_global_roots(state.home))
        if not (path.exists() or path.is_symlink()):
            continue
        if not (
            adapter_state["points_to_global"]
            or adapter_state["is_scoped_symlink_adapter"]
            or adapter_state["is_portable_copy"]
        ):
            continue
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
        removed.append(str(path))
    return removed


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
            "No `.codex/skills` or other repo adapter paths are created.",
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
        if state.global_preset is not None or state.preset is not None:
            default_packs = resolve_package_selection(
                state.repo_root,
                preset=state.global_preset or state.preset,
                skills=state.global_skills if state.global_skills is not None else state.skills,
                skill_classes=state.global_skill_classes if state.global_skill_classes is not None else state.skill_classes,
                skill_tags=state.global_skill_tags if state.global_skill_tags is not None else state.skill_tags,
                exclude_skills=state.global_exclude_skills if state.global_exclude_skills is not None else state.exclude_skills,
                target_root=state.caller_directory,
            ).packs
        else:
            default_packs = ["core"]
            state.global_preset = "core"
    selected = choose_many_checkbox(
        term,
        "Select global packs",
        _pack_choices(state.repo_root),
        default=default_packs,
        allow_none=True,
        decides="Which baseline packages are kept in the managed Localsetup library.",
        suggested_reason="Core is the conservative global baseline unless prior registry settings or CLI selectors are present.",
        help_text="Choose one or more packs for the shared package library. Repo adapter visibility is selected separately.",
    )
    if isinstance(selected, str) and selected in {BACK, CANCEL}:
        return selected
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
    global_packs = state.global_packs if state.global_packs is not None else (state.packs if state.packs is not None else ["core"])
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
        global_preset=state.global_preset,
        global_skills=state.global_skills,
        global_skill_classes=state.global_skill_classes,
        global_skill_tags=state.global_skill_tags,
        global_exclude_skills=state.global_exclude_skills,
        repo_packs=repo_packs,
        repo_preset=state.repo_preset,
        repo_skills=state.repo_skills,
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
            str(state.repo_root / "_localsetup/tools/localsetup_v3.py"),
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


def _apply_and_show_result(term: TerminalWizard, state: WizardState) -> int:
    term.title("Applying")
    target_root = state.target_directory
    platforms = state.platforms or []
    global_packs = state.global_packs if state.global_packs is not None else (state.packs if state.packs is not None else ["core"])
    repo_packs = state.repo_packs if state.repo_packs is not None else (state.packs if platforms and state.packs is not None else [])
    try:
        dependency_info = (
            ensure_dependencies(
                state.repo_root,
                mode=state.dependency_mode,
                data_root=state.home / ".local" / "share" / "localsetup",
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
            skill_classes=state.skill_classes,
            skill_tags=state.skill_tags,
            exclude_skills=state.exclude_skills,
            global_packs=global_packs,
            global_preset=state.global_preset,
            global_skills=state.global_skills,
            global_skill_classes=state.global_skill_classes,
            global_skill_tags=state.global_skill_tags,
            global_exclude_skills=state.global_exclude_skills,
            repo_packs=repo_packs,
            repo_preset=state.repo_preset,
            repo_skills=state.repo_skills,
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
                str(state.repo_root / "_localsetup/tools/localsetup_v3.py"),
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
        term.status_line("ok", "Localsetup installed successfully.")
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
    skill_classes: list[str] | None = None,
    skill_tags: list[str] | None = None,
    exclude_skills: list[str] | None = None,
    global_packs: list[str] | None = None,
    global_preset: str | None = None,
    global_skills: list[str] | None = None,
    global_skill_classes: list[str] | None = None,
    global_skill_tags: list[str] | None = None,
    global_exclude_skills: list[str] | None = None,
    repo_packs: list[str] | None = None,
    repo_preset: str | None = None,
    repo_skills: list[str] | None = None,
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
        skill_classes=skill_classes,
        skill_tags=skill_tags,
        exclude_skills=exclude_skills,
        global_packs=global_packs,
        global_preset=global_preset,
        global_skills=global_skills,
        global_skill_classes=global_skill_classes,
        global_skill_tags=global_skill_tags,
        global_exclude_skills=global_exclude_skills,
        repo_packs=repo_packs,
        repo_preset=repo_preset,
        repo_skills=repo_skills,
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
