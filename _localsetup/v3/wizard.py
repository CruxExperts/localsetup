from __future__ import annotations

from dataclasses import dataclass
import sys
from pathlib import Path
from typing import TextIO

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


class TerminalWizard:
    def __init__(self, input_stream: TextIO, output_stream: TextIO, *, color: bool | None = None) -> None:
        self.input = input_stream
        self.output = output_stream
        self.color = color if color is not None else self._supports_color(output_stream)

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

    def prompt(self, prompt: str, *, default: str | None = None) -> str:
        suffix = f" [{default}]" if default else ""
        while True:
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


def choose_one(
    term: TerminalWizard,
    prompt: str,
    choices: list[tuple[str, str]],
    *,
    default: str,
) -> str:
    valid = {str(i): value for i, (value, _) in enumerate(choices, start=1)}
    labels = {value: label for value, label in choices}
    default_number = next((num for num, value in valid.items() if value == default), "1")
    for i, (value, label) in enumerate(choices, start=1):
        marker = " (default)" if value == default else ""
        term.write(f"  {i}. {label}{marker}")
    while True:
        answer = term.prompt(prompt, default=default_number)
        if answer in {BACK, CANCEL}:
            return answer
        if answer in valid:
            return valid[answer]
        for value, label in labels.items():
            if answer.lower() in {value.lower(), label.lower()}:
                return value
        term.write("Choose one of the listed numbers, or enter b to go back / q to cancel.")


def choose_many(
    term: TerminalWizard,
    prompt: str,
    choices: list[tuple[str, str]],
    *,
    default: list[str],
    allow_none: bool = True,
) -> list[str] | str:
    valid = {str(i): value for i, (value, _) in enumerate(choices, start=1)}
    labels = {value: label for value, label in choices}
    default_numbers = [num for num, value in valid.items() if value in default]
    default_text = ",".join(default_numbers) if default_numbers else "none"
    for i, (value, label) in enumerate(choices, start=1):
        marker = " (default)" if value in default else ""
        term.write(f"  {i}. {label}{marker}")
    if allow_none:
        term.write("  0. None")
    while True:
        answer = term.prompt(prompt, default=default_text)
        if answer in {BACK, CANCEL}:
            return answer
        if allow_none and answer.lower() in {"none", "0"}:
            return []
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
        term.write("Choose comma-separated numbers from the list, or enter b to go back / q to cancel.")


def _platform_choices(repo_root: Path) -> list[tuple[str, str]]:
    return [(platform.platform_id, PLATFORM_LABELS.get(platform.platform_id, platform.platform_id)) for platform in load_platforms(repo_root)]


def _pack_choices(repo_root: Path) -> list[tuple[str, str]]:
    pack = load_pack_config(repo_root)
    names = list(dict.fromkeys(["core", *pack.optional_packs, *pack.packs.keys()]))
    return [(name, name) for name in names]


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
    term.write("This wizard installs the managed Localsetup skill library and can attach adapters for agent tools.")
    term.write(f"Source checkout: {state.repo_root}")
    term.write(f"Managed library: {_global_root(state.repo_root, state.home)}")
    term.write("It will show a review screen before anything is applied.")
    return term.prompt("Press Enter to continue, or q to cancel", default="continue")


def _source_step(term: TerminalWizard, state: WizardState) -> str:
    term.title("Source")
    term.write(f"Using Localsetup source: {state.repo_root}")
    term.write("Explicit --directory values are used as-is; raw installs use the managed source checkout.")
    return term.prompt("Press Enter to continue", default="continue")


def _mode_step(term: TerminalWizard, state: WizardState) -> str:
    term.title("Install Mode")
    choices = [
        ("global", "Global library only"),
        ("current", f"Attach adapters to current directory ({state.caller_directory})"),
        ("other", "Attach adapters to another target directory"),
    ]
    default = "global"
    if state.target_directory_is_explicit and state.target_directory is not None:
        choices = [
            ("global", "Global library only"),
            ("explicit", f"Attach adapters to target directory ({state.target_directory})"),
            ("current", f"Attach adapters to current directory ({state.caller_directory})"),
            ("other", "Attach adapters to another target directory"),
        ]
        default = "explicit"
    elif (not state.target_directory_is_explicit and state.target_directory is not None) or state.platforms:
        default = "current"
    choice = choose_one(
        term,
        "Install mode",
        choices,
        default=default,
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
        answer = term.prompt("Target directory")
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
    )
    if isinstance(selected, str) and selected in {BACK, CANCEL}:
        return selected
    state.platforms = selected
    return "continue"


def _pack_step(term: TerminalWizard, state: WizardState) -> str:
    term.title("Skill Packs")
    selected = choose_many(term, "Select packs", _pack_choices(state.repo_root), default=state.packs or ["core"], allow_none=False)
    if isinstance(selected, str) and selected in {BACK, CANCEL}:
        return selected
    state.packs = selected
    return "continue"


def _options_step(term: TerminalWizard, state: WizardState) -> str:
    term.title("Options")
    attach = choose_one(
        term,
        "Adapter mode",
        [("symlink", "Symlink adapters"), ("portable", "Portable adapter copies")],
        default=state.attach_mode,
    )
    if attach in {BACK, CANCEL}:
        return attach
    deps = choose_one(
        term,
        "Dependency mode",
        [("prompt-only", "Prompt only"), ("managed-venv", "Managed virtual environment")],
        default=state.dependency_mode,
    )
    if deps in {BACK, CANCEL}:
        return deps
    state.attach_mode = attach
    state.dependency_mode = deps
    return "continue"


def _review_step(term: TerminalWizard, state: WizardState) -> str:
    term.title("Review")
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
        return term.prompt("Enter b to change options or q to cancel", default="b")
    confirm = term.prompt("Apply this install? Type yes to continue", default="no")
    if confirm in {BACK, CANCEL}:
        return confirm
    return "apply" if confirm.lower() == "yes" else BACK


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
    steps = [_show_welcome, _source_step, _mode_step, _platform_step, _pack_step, _options_step, _review_step]
    index = 0
    try:
        while index < len(steps):
            result = steps[index](term, state)
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
