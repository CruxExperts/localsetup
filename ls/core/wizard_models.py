"""Wizard models, constants, and terminal rendering."""

from __future__ import annotations

from dataclasses import dataclass
import locale
import os
import shutil
import sys
import textwrap
from pathlib import Path
from typing import Sequence, TextIO

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

WELCOME_BANNER = "LocalSetup installer"

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
    workflows: list[str] | None = None
    skill_classes: list[str] | None = None
    skill_tags: list[str] | None = None
    exclude_skills: list[str] | None = None
    global_packs: list[str] | None = None
    global_preset: str | None = None
    global_skills: list[str] | None = None
    global_workflows: list[str] | None = None
    global_skill_classes: list[str] | None = None
    global_skill_tags: list[str] | None = None
    global_exclude_skills: list[str] | None = None
    repo_packs: list[str] | None = None
    repo_preset: str | None = None
    repo_skills: list[str] | None = None
    repo_workflows: list[str] | None = None
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
