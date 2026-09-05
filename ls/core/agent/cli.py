"""LSCli's provider-free command boundary."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

from ..branding import CLI_COMMAND, CLI_NAME, PRODUCT_NAME
from ..framework_version import framework_version
from .diagnostics import inspect


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=CLI_COMMAND, description=f"{CLI_NAME}: the integrated {PRODUCT_NAME} agent CLI")
    parser.add_argument("--version", action="version", version=f"{CLI_NAME} ({PRODUCT_NAME}) {framework_version()}")
    commands = parser.add_subparsers(dest="command")
    doctor = commands.add_parser("doctor", help="Inspect installed payload and execution readiness without provider access")
    doctor.add_argument("--format", choices=("text", "json"), default="text")
    setup = commands.add_parser("setup", help="Plan or apply an explicit offline runtime installation")
    mode = setup.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--apply", action="store_true")
    setup.add_argument("--wheel", type=Path, required=True)
    setup.add_argument("--sha256", required=True)
    setup.add_argument("--wheelhouse", type=Path, required=True)
    setup.add_argument("--runtime-root", type=Path)
    setup.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args(argv)
    if args.command == "setup":
        from .diagnostics import locations
        from .runtime_install import install, plan
        root = args.runtime_root or Path(locations(Path.home())["runtimes"])
        inputs = (root, args.wheel, args.sha256, args.wheelhouse, Path.cwd())
        try:
            result = install(*inputs, timeout=args.timeout) if args.apply else plan(*inputs)
        except KeyboardInterrupt:
            print(f"{CLI_NAME} setup cancelled; inspect retained installation state.", file=sys.stderr)
            return 130
        except (OSError, ValueError, TypeError, RuntimeError, RecursionError, subprocess.SubprocessError) as exc:
            print(f"{CLI_NAME} setup failed: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(result, sort_keys=True))
        return 0
    if args.command is None:
        print(f"{CLI_NAME}: agent execution is not available yet; run '{CLI_COMMAND} doctor' for readiness details.", file=sys.stderr)
        return 3
    report = inspect()
    if args.format == "json":
        print(json.dumps(report, sort_keys=True))
    else:
        print(f"{CLI_NAME} ({PRODUCT_NAME}) {report['framework_version']}")
        print(f"SDK payload: {report['sdk_payload']}; execution: unavailable")
        for issue in report["issues"]:
            print(f"- {issue}")
        for name, path in report["locations"].items():
            print(f"{name}: {json.dumps(path)}")
    return 3 if not report["execution_available"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
