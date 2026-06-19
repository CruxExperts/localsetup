"""CLI for tmux terminal mode."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .constants import DEFAULT_MODE, DEFAULT_RULES_FILE, DEFAULT_SESSION, IDE_SETTINGS_CANDIDATES, TOOL_VERSION
from .io import die, dry, info, ok
from .layers import (
    apply_ide_layer,
    apply_rule_layer,
    apply_shell_layer,
    default_shell_rc,
    detect_settings_file,
    detect_existing_settings_file,
    ide_layer_active,
    remove_ide_layer,
    remove_rule_layer,
    remove_shell_layer,
    resolve_tmux,
    rule_layer_active,
    shell_layer_active,
    terminal_mode_status,
)

DESCRIPTION = """tmux_terminal_mode - Toggleable framework feature: tmux-default terminal mode.

Sub-commands:
  enable   Apply Layer 1 (ide or shell) + Layer 2 (agent rule).
  disable  Remove Layer 1 + Layer 2. Restore backups where available.
  status   Report which layers are active.

Run with --help for full flag reference.
"""


def _settings_path_from_args(args: argparse.Namespace) -> Path:
    settings_path = Path(args.settings_file).expanduser()
    if settings_path.exists():
        return settings_path
    if settings_path.parent.exists():
        try:
            settings_path.write_text("{}\n", encoding="utf-8")
            info(f"Created empty settings file: {settings_path}")
            return settings_path
        except OSError as exc:
            die(f"Could not create {settings_path}: {exc}")
    die(
        f"--settings-file {settings_path} does not exist and its parent "
        "directory does not exist either.\n"
        "  Create the directory first or use --mode shell."
    )


def _detect_or_die_settings_file() -> Path:
    settings_path = detect_settings_file()
    if settings_path:
        return settings_path
    die(
        "No IDE settings directory detected. Checked:\n"
        + "\n".join(f"  {c}" for c in IDE_SETTINGS_CANDIDATES)
        + "\n\nNone of the expected parent directories exist on this machine.\n"
        "Use --settings-file <path> to specify one, or use --mode shell."
    )


def cmd_enable(args: argparse.Namespace) -> int:
    mode = args.mode
    session = args.session
    dry_run = args.dry_run
    rules_path = Path(args.rules_file).expanduser()

    tmux_path = resolve_tmux()
    info(f"tmux: {tmux_path}")

    if mode == "ide":
        settings_path = _settings_path_from_args(args) if args.settings_file else _detect_or_die_settings_file()
        info(f"Mode: ide  |  settings: {settings_path}  |  session: {session}")
        apply_ide_layer(settings_path, session, tmux_path, dry_run)
    elif mode == "shell":
        rc_path = Path(args.shell_rc).expanduser() if args.shell_rc else default_shell_rc()
        info(f"Mode: shell  |  rc: {rc_path}  |  session: {session}")
        apply_shell_layer(rc_path, session, dry_run)

    apply_rule_layer(rules_path, dry_run)

    if not dry_run:
        print()
        ok("tmux-default terminal mode enabled.")
        if mode == "ide":
            print("  Restart the IDE terminal panel for the new profile to appear.")
        elif mode == "shell":
            print("  Open a new shell session to activate auto-attach.")
            print("  NOTE: shell mode uses 'exec tmux', so a new terminal is the only")
            print("  clean way back to a plain shell after disabling.")
    else:
        print()
        dry("Dry-run complete. No files were modified.")
    return 0


def cmd_disable(args: argparse.Namespace) -> int:
    mode = args.mode
    dry_run = args.dry_run
    rules_path = Path(args.rules_file).expanduser()
    anything_done = False

    if mode == "ide":
        settings_path = Path(args.settings_file).expanduser() if args.settings_file else detect_settings_file()
        if not settings_path:
            settings_path = _settings_path_with_backup()
        if settings_path:
            was_active = ide_layer_active(settings_path) is not None or _backup_exists(settings_path)
            remove_ide_layer(settings_path, dry_run)
            anything_done = anything_done or was_active
        else:
            info("Nothing to do for Layer 1a (no IDE settings file found).")
    elif mode == "shell":
        rc_path = Path(args.shell_rc).expanduser() if args.shell_rc else default_shell_rc()
        was_active = shell_layer_active(rc_path) is not None
        remove_shell_layer(rc_path, dry_run)
        anything_done = anything_done or was_active

    rule_was_active = rule_layer_active(rules_path)
    remove_rule_layer(rules_path, dry_run)
    anything_done = anything_done or rule_was_active

    if not anything_done:
        print()
        info("Nothing to do. tmux-default terminal mode was not enabled.")
        return 0

    if not dry_run:
        print()
        ok("tmux-default terminal mode disabled.")
        if mode == "ide":
            print("  Restart the IDE terminal panel to return to the default shell.")
        elif mode == "shell":
            print("  Open a new shell session to get a plain shell.")
    else:
        print()
        dry("Dry-run complete. No files were modified.")
    return 0


def _backup_exists(path: Path) -> bool:
    return path.with_suffix(path.suffix + ".tmux-mode.bak").exists()


def _settings_path_with_backup() -> Path | None:
    for candidate in IDE_SETTINGS_CANDIDATES:
        p = Path(candidate).expanduser()
        if _backup_exists(p):
            return p
    return None


def cmd_status(args: argparse.Namespace, *, tools_dir: Path | None = None) -> int:
    rules_path = Path(args.rules_file).expanduser()
    settings_path = Path(args.settings_file).expanduser() if args.settings_file else detect_existing_settings_file()
    rc_path = Path(args.shell_rc).expanduser() if args.shell_rc else default_shell_rc()
    status = terminal_mode_status(
        settings_path=settings_path,
        rc_path=rc_path,
        rules_path=rules_path,
        tools_dir=tools_dir or _default_tools_dir(),
    )

    if args.json:
        print(json.dumps(status, sort_keys=True))
        return 0

    ide_session = status["layers"]["ide"]["session"]
    shell_session = status["layers"]["shell"]["session"]
    rule_active = status["layers"]["rules"]["active"]
    tmux_ops = status["layers"]["tmux_ops"]["path"]

    if ide_session:
        detected_mode = "ide"
        detected_session = ide_session
    elif shell_session:
        detected_mode = "shell"
        detected_session = shell_session
    else:
        detected_mode = "none"
        detected_session = "-"

    print()
    print("tmux-default terminal mode status")
    print(f"  Mode detected:           {detected_mode}")
    print(f"  Session name:            {detected_session}")

    if ide_session:
        settings_label = str(settings_path) if settings_path else "unknown"
        print(f"  Layer 1a (IDE profile):  ACTIVE   [tmux-session -> {ide_session}, settings: {settings_label}]")
    else:
        print("  Layer 1a (IDE profile):  INACTIVE")

    if shell_session:
        print(f"  Layer 1b (shell RC):     ACTIVE   [session: {shell_session}, rc: {rc_path}]")
    else:
        print("  Layer 1b (shell RC):     INACTIVE")

    if rule_active:
        print(f"  Layer 2  (agent rule):   ACTIVE   [rules: {rules_path}]")
    else:
        print("  Layer 2  (agent rule):   INACTIVE")

    if tmux_ops:
        print(f"  Layer 3  (tmux_ops):     PRESENT  [{tmux_ops}]")
    else:
        print("  Layer 3  (tmux_ops):     MISSING  (expected at _localsetup/tools/tmux_ops)")
    print()
    return 0


def _default_tools_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "tools"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tmux_terminal_mode",
        description=DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {TOOL_VERSION}")

    sub = parser.add_subparsers(dest="subcommand", metavar="SUBCOMMAND")
    sub.required = True

    enable = sub.add_parser("enable", help="Apply tmux-default terminal mode")
    _add_common(enable)
    enable.set_defaults(func=cmd_enable)

    disable = sub.add_parser("disable", help="Remove tmux-default terminal mode")
    _add_common(disable)
    disable.set_defaults(func=cmd_disable)

    status = sub.add_parser("status", help="Report which layers are active")
    status.add_argument("--settings-file", metavar="PATH", help="IDE settings.json path (auto-detected if omitted)")
    status.add_argument("--shell-rc", metavar="PATH", help="Shell RC file path (default: ~/.bashrc or ~/.bash_profile on macOS)")
    status.add_argument("--rules-file", default=DEFAULT_RULES_FILE, metavar="PATH", help=f"Agent rules file (default: {DEFAULT_RULES_FILE})")
    status.add_argument("--json", action="store_true", help="Emit machine-readable read-only status")
    status.set_defaults(func=cmd_status)
    return parser


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--mode", choices=["ide", "shell"], default=DEFAULT_MODE, help=f"Layer 1 variant (default: {DEFAULT_MODE})")
    parser.add_argument("--session", default=DEFAULT_SESSION, metavar="NAME", help=f"tmux session name (default: {DEFAULT_SESSION})")
    parser.add_argument("--settings-file", metavar="PATH", help="IDE settings.json path (ide mode; auto-detected if omitted)")
    parser.add_argument("--shell-rc", metavar="PATH", help="Shell RC file path (shell mode; default: ~/.bashrc or ~/.bash_profile on macOS)")
    parser.add_argument("--rules-file", default=DEFAULT_RULES_FILE, metavar="PATH", help=f"Agent rules file (default: {DEFAULT_RULES_FILE})")
    parser.add_argument("--dry-run", action="store_true", help="Print planned changes without modifying any file")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
