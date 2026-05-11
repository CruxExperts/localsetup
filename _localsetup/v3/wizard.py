from __future__ import annotations

from dataclasses import dataclass
import sys
from pathlib import Path
from typing import Sequence, TextIO

from .apply import apply_plan
from .dependencies import ensure_dependencies
from .doctor import run_doctor
from .manifests import load_pack_config, load_platforms
from .paths import expand_user_path
from .plan import build_install_plan
from .shell import register_shell_command
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
    platforms: list[str] | None = None
    platforms_were_provided: bool = False
    packs: list[str] | None = None
    attach_mode: str = "symlink"
    dependency_mode: str = "prompt-only"
    register_shell: bool = True
    detail_mode: bool = True


class TerminalWizard:
    def __init__(self, input_stream: TextIO, output_stream: TextIO, *, color: bool | None = None) -> None:
        self.input = input_stream
        self.output = output_stream
        self.color = color if color is not None else self._supports_color(output_stream)
        self.detail_mode = True

    @staticmethod
    def _supports_color(stream: TextIO) -> bool:
        return hasattr(stream, "isatty") and stream.isatty()

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

    def title(self, text: str) -> None:
        self.write("")
        self.write(self.style(text, "1;36"))
        self.write(self.style("-" * len(text), "36"))

    def write(self, text: str = "") -> None:
        print(text, file=self.output)

    def prompt(self, prompt: str, *, default: str | None = None, footer: str | None = None) -> str:
        suffix = f" [{default}]" if default else ""
        while True:
            if footer:
                self.write(self.style(footer, "2"))
            self.output.write(f"{prompt}{suffix}: ")
            self.output.flush()
            line = self.input.readline()
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


def open_tty() -> TerminalWizard:
    try:
        tty_in = open("/dev/tty", "r", encoding="utf-8", errors="replace")
        tty_out = open("/dev/tty", "w", encoding="utf-8", errors="replace")
    except OSError as exc:
        raise RuntimeError(
            "interactive installer requires a terminal. Run with a TTY, or use --non-interactive --yes for automation."
        ) from exc
    return TerminalWizard(tty_in, tty_out)


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
        term.write(f"Decides: {decides}")
    if suggested:
        reason = suggested_reason or suggested.best_for
        term.write(f"Suggested: {suggested.label} - {reason}")
    if decides or suggested:
        term.write("")


def _render_choices(term: TerminalWizard, choices: list[Choice], *, default_values: set[str]) -> None:
    for i, choice in enumerate(choices, start=1):
        marker = " (suggested)" if choice.value in default_values else ""
        term.write(f"  {i}. {choice.label}{marker}")
        term.write(f"     {choice.summary}")
        if term.detail_mode:
            term.write(f"     Does: {choice.effect}")
            term.write(f"     Choose when: {choice.best_for}")
            term.write(f"     Tradeoff: {choice.tradeoff}")
            if choice.caution:
                term.write(f"     Caution: {choice.caution}")


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
    return SHORTCUT_FOOTER


def _continue_footer(term: TerminalWizard) -> str:
    return SHORTCUT_FOOTER


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
            "managed-venv",
            "Managed virtual environment",
            "Prepares Localsetup's managed Python environment.",
            "Creates or updates the Python environment used by Localsetup helper tools.",
            "You want the installer to prepare Python tooling now.",
            "Takes longer and changes the managed environment under your home directory.",
        ),
    ]


def _global_root(repo_root: Path, home: Path) -> Path:
    return expand_user_path(load_pack_config(repo_root).global_root, home)


def _action_summary(actions: list[object]) -> list[str]:
    labels = {
        "ensure_dir": "Ensure managed skill library exists",
        "write_registry": "Write Localsetup registry",
        "install_skills": "Install selected skills",
        "install_workflows": "Install selected workflows",
        "attach_repo_path": "Attach selected adapter",
    }
    return [f"{labels.get(getattr(action, 'kind'), getattr(action, 'kind'))}: {getattr(action, 'path')}" for action in actions]


def _show_welcome(term: TerminalWizard, state: WizardState) -> str:
    term.title("Localsetup v3 installer")
    term.write("Decides: Starts a guided install session and confirms the source checkout.")
    term.write("This wizard installs the managed Localsetup skill library and can attach adapters for agent tools.")
    term.write(f"Source checkout: {state.repo_root}")
    term.write(f"Managed library: {_global_root(state.repo_root, state.home)}")
    term.write("It will show a review screen before anything is applied.")
    return _continue_prompt(
        term,
        "Press Enter to continue",
        help_text="This first screen only orients you. Nothing changes until the Review screen is applied.",
        detail_text="Localsetup keeps a managed shared library under your home directory and can optionally attach repo adapter paths.",
    )


def _source_step(term: TerminalWizard, state: WizardState) -> str:
    term.title("Source")
    term.write("Decides: Which Localsetup checkout provides the installer files and shipped skills.")
    term.write(f"Using Localsetup source: {state.repo_root}")
    term.write("Explicit --directory values are used as-is; raw installs use the managed source checkout.")
    if term.detail_mode:
        term.write("Does: Reads manifests, skills, workflows, and installer code from this checkout.")
        term.write("Choose when: This source path is the Localsetup version you want to install from.")
        term.write("Tradeoff: A stale source checkout can install stale skills; refresh the source first if that is a concern.")
    return _continue_prompt(
        term,
        "Press Enter to continue",
        help_text="Source is informational here. Use b to return from the next step or q to cancel before applying.",
        detail_text="The source checkout is not modified by this step.",
    )


def _mode_step(term: TerminalWizard, state: WizardState) -> str:
    term.title("Install Mode")
    choices = [
        Choice(
            "global",
            "Global library only",
            "Safest default; updates shared Localsetup skills without repo adapter paths.",
            "Installs or refreshes the managed skill library under your home directory.",
            "You want Localsetup available globally and do not need this repo wired to an agent tool yet.",
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
    default = "global"
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
        "Install mode",
        choices,
        default=default,
        decides="Whether this run only refreshes the shared library or also wires a repo.",
        suggested_reason="This matches the command-line context and avoids surprising repo changes.",
        help_text="Pick global for the least invasive install, current for this repo, or another target when preparing a different path.",
    )
    if choice in {BACK, CANCEL}:
        return choice
    if choice == "global":
        state.target_directory = None
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
    if state.target_directory is None:
        state.platforms = []
        return "continue"
    term.title("Platforms")
    default_platforms = state.platforms or (["codex"] if not state.target_directory_is_explicit else [])
    selected = choose_many(
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
    return "continue"


def _pack_step(term: TerminalWizard, state: WizardState) -> str:
    term.title("Skill Packs")
    selected = choose_many(
        term,
        "Select packs",
        _pack_choices(state.repo_root),
        default=state.packs or ["core"],
        allow_none=False,
        decides="Which Localsetup skills and workflows are installed into the managed library.",
        suggested_reason="Core is the normal starter pack for regular use.",
        help_text="Choose one or more packs by number or name. Core is recommended unless you know you need a specialized pack.",
    )
    if isinstance(selected, str) and selected in {BACK, CANCEL}:
        return selected
    state.packs = selected
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
        help_text="Prompt-only reports needs without installing. Managed virtual environment prepares Localsetup's Python tooling.",
    )
    if deps in {BACK, CANCEL}:
        return deps
    state.attach_mode = attach
    state.dependency_mode = deps
    return "continue"


def _review_step(term: TerminalWizard, state: WizardState) -> str:
    term.title("Review")
    term.write("Decides: Whether the planned install should be applied.")
    target_root = state.target_directory
    platforms = state.platforms or []
    packs = state.packs or ["core"]
    plan = build_install_plan(
        state.repo_root,
        home=state.home,
        packs=packs,
        attach_mode=state.attach_mode,
        platform_ids=platforms,
        target_root=target_root,
    )
    doctor = run_doctor(
        state.repo_root,
        home=state.home,
        packs=packs,
        platform_ids=platforms,
        dependency_mode=state.dependency_mode,
        target_root=target_root,
    )
    term.write(f"Source: {state.repo_root}")
    term.write(f"Target: {target_root or state.repo_root} ({'global library only' if not platforms else 'adapters selected'})")
    term.write(f"Home library: {_global_root(state.repo_root, state.home)}")
    term.write(f"Platforms: {', '.join(platforms) if platforms else 'none'}")
    term.write(f"Packs: {', '.join(packs)}")
    term.write(f"Adapter mode: {state.attach_mode}")
    term.write(f"Dependency mode: {state.dependency_mode}")
    if term.detail_mode:
        term.write("Does: Shows source, target, packs, adapter mode, dependency mode, and concrete filesystem actions before changes.")
        term.write("Choose when: Continue only if this screen matches the install you intended.")
        term.write("Tradeoff: Going back is cheap now; after apply, rollback uses the generated lockfile.")
    term.write("")
    term.write("Planned actions:")
    for line in _action_summary(plan.actions):
        term.write(f"  - {line}")
    if doctor["warnings"]:
        term.write("")
        term.write(term.style("Warnings:", "33"))
        for warning in doctor["warnings"]:
            term.write(f"  - {warning}")
    if doctor["blockers"]:
        term.write("")
        term.write(term.style("Blockers:", "31"))
        for blocker in doctor["blockers"]:
            term.write(f"  - {blocker}")
        term.write("Diagnostic command:")
        cmd = [
            "python3",
            str(state.repo_root / "_localsetup/tools/localsetup_v3.py"),
            "--home",
            str(state.home),
            "--repo",
            str(state.repo_root),
        ]
        if target_root:
            cmd.extend(["--target-directory", str(target_root)])
        cmd.extend(["doctor", "--dependency-mode", state.dependency_mode, "--packs", *packs])
        if platforms:
            cmd.extend(["--platforms", *platforms])
        term.write("  " + " ".join(cmd))
        return _blocker_prompt(term)
    return _confirm_apply(term)


def _apply_and_show_result(term: TerminalWizard, state: WizardState) -> int:
    term.title("Applying")
    target_root = state.target_directory
    platforms = state.platforms or []
    packs = state.packs or ["core"]
    try:
        dependency_info = (
            ensure_dependencies(state.repo_root, mode=state.dependency_mode)
            if state.dependency_mode != "prompt-only"
            else None
        )
        plan = build_install_plan(
            state.repo_root,
            home=state.home,
            packs=packs,
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
        verify = verify_install(state.repo_root, state.home, platform_ids=platforms, target_root=target_root)
    except Exception as exc:
        term.write(term.style("Install failed.", "31"))
        term.write(str(exc))
        term.write("Diagnostic command:")
        term.write(
            "  python3 "
            + str(state.repo_root / "_localsetup/tools/localsetup_v3.py")
            + f" --home {state.home} --repo {state.repo_root} doctor"
        )
        return 2

    term.title("Result")
    term.write("Decides: Confirms what was installed and which follow-up commands are useful.")
    if verify["ok"]:
        term.write(term.style("Localsetup installed successfully.", "32"))
    else:
        term.write(term.style("Install finished, but verification reported issues.", "33"))
    term.write(f"Managed library: {_global_root(state.repo_root, state.home)}")
    term.write(f"Target: {target_root or state.repo_root}")
    term.write(f"Platforms: {', '.join(platforms) if platforms else 'none'}")
    if shell_result:
        term.write(f"Command: {state.home / '.local/bin/localsetup'}")
        for warning in shell_result.get("warnings", []):
            term.write(f"Warning: {warning}")
    term.write("")
    term.write("Next commands:")
    verify_cmd = ["localsetup", "verify"]
    if platforms:
        verify_cmd.extend(["--tools", ",".join(platforms)])
    term.write("  " + " ".join(verify_cmd))
    term.write("  localsetup rollback")
    if result.get("lockfile"):
        term.write(f"Lockfile: {result['lockfile']}")
    if term.detail_mode:
        term.write("Does: Verification checked the managed library and selected adapter paths after applying the plan.")
        term.write("Choose when: Use the verify command later if you move files or change installed platforms.")
        term.write("Tradeoff: Rollback uses the lockfile from this run, so keep it with the prepared repo.")
    return 0 if verify["ok"] else 1


def run_wizard(
    *,
    repo_root: Path,
    home: Path,
    caller_directory: Path | None = None,
    target_directory: Path | None = None,
    target_directory_is_explicit: bool = False,
    platforms: list[str] | None = None,
    packs: list[str] | None = None,
    attach_mode: str = "symlink",
    dependency_mode: str = "prompt-only",
    register_shell: bool = True,
    terminal: TerminalWizard | None = None,
) -> int:
    term = terminal or open_tty()
    state = WizardState(
        repo_root=repo_root.resolve(),
        home=home.expanduser().resolve(),
        caller_directory=(caller_directory or Path.cwd()).expanduser().resolve(),
        target_directory=target_directory.expanduser().resolve() if target_directory else None,
        target_directory_is_explicit=target_directory_is_explicit,
        platforms=platforms,
        platforms_were_provided=platforms is not None,
        packs=packs,
        attach_mode=attach_mode,
        dependency_mode=dependency_mode,
        register_shell=register_shell,
    )
    term.detail_mode = state.detail_mode
    steps = [_show_welcome, _source_step, _mode_step, _platform_step, _pack_step, _options_step, _review_step]
    index = 0
    try:
        while index < len(steps):
            result = steps[index](term, state)
            state.detail_mode = term.detail_mode
            if result == CANCEL:
                term.write("Install canceled. No changes were applied.")
                return 130
            if result == BACK:
                index = max(0, index - 1)
                continue
            if result == "apply":
                return _apply_and_show_result(term, state)
            index += 1
        return 1
    finally:
        if terminal is None:
            term.close()
