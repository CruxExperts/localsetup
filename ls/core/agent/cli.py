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
    mode.add_argument("--reselect", metavar="SHA256")
    setup.add_argument("--wheel", type=Path)
    setup.add_argument("--sha256")
    setup.add_argument("--wheelhouse", type=Path)
    setup.add_argument("--sandbox-bundle", type=Path)
    setup.add_argument("--sandbox-sha256")
    setup.add_argument("--runtime-root", type=Path)
    setup.add_argument("--timeout", type=float, default=300)
    sessions=commands.add_parser('sessions',help='List local session metadata without provider access')
    sessions.add_argument('--state-root',type=Path)
    sessions.add_argument('--format',choices=('text','json'),default='text')
    run = commands.add_parser('run', help='Run with an explicit profile and task grant in the protected runtime')
    from .run_options import arguments
    arguments(run)
    args = parser.parse_args(argv)
    if args.command == 'sessions':
        from .diagnostics import locations
        from .session_index import scan
        from .run_io import Streams, safe
        import threading
        import time
        try:
            root=args.state_root or Path(locations(Path.home())['state'])
            expires=time.monotonic()+5
            report=scan(root/'sessions',expires=expires)
            text=json.dumps(report,ensure_ascii=True)+'\n' if args.format=='json' else ''.join(
                safe(f"{item.get('session',item['storage_id'])}: {item['status']}")+'\n' for item in report['sessions'])
            Streams(expires,threading.Event()).write(text)
            return 0
        except KeyboardInterrupt:return 130
        except (OSError,ValueError,TypeError,RecursionError):
            from .run_cli import failure
            return failure('text',0,'failed',2,'session inventory failed; verify private state integrity.')
    if args.command == 'run':
        from .run_cli import launch
        try:
            launch((sys.argv[1:] if argv is None else argv)[1:],args)
        except (OSError,ValueError,TypeError,RuntimeError):
            print(f"{CLI_NAME} run could not start; verify the selected profile, credential and installed runtime.",file=sys.stderr)
            return 3
    if args.command == "setup":
        from .diagnostics import locations
        from .runtime_install import install, plan, reselect
        root = args.runtime_root or Path(locations(Path.home())["runtimes"])
        if args.reselect and any((args.wheel, args.sha256, args.wheelhouse, args.sandbox_bundle, args.sandbox_sha256)):
            setup.error("--reselect cannot be combined with installation inputs")
        if not args.reselect and not all((args.wheel, args.sha256, args.wheelhouse)):
            setup.error("--plan and --apply require --wheel, --sha256 and --wheelhouse")
        if (args.sandbox_bundle is None) != (args.sandbox_sha256 is None):
            setup.error("--sandbox-bundle and --sandbox-sha256 must be supplied together")
        native_inputs = {} if args.sandbox_bundle is None else {
            'sandbox_bundle': args.sandbox_bundle, 'sandbox_sha256': args.sandbox_sha256}
        inputs = (root, args.wheel, args.sha256, args.wheelhouse, Path.cwd())
        try:
            if args.reselect:
                result = reselect(root, args.reselect, timeout=args.timeout)
            else:
                result = install(*inputs, timeout=args.timeout, **native_inputs) if args.apply else plan(*inputs, **native_inputs)
        except KeyboardInterrupt:
            print(f"{CLI_NAME} setup cancelled; inspect retained installation state.", file=sys.stderr)
            return 130
        except (OSError, ValueError, TypeError, RuntimeError, RecursionError, subprocess.SubprocessError) as exc:
            print(f"{CLI_NAME} setup failed: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(result, sort_keys=True))
        return 0
    if args.command is None:
        print(f"{CLI_NAME}: use '{CLI_COMMAND} run --help' for explicit coding grants or '{CLI_COMMAND} doctor' for readiness.", file=sys.stderr)
        return 3
    report = inspect()
    if args.format == "json":
        print(json.dumps(report, sort_keys=True))
    else:
        print(f"{CLI_NAME} ({PRODUCT_NAME}) {report['framework_version']}")
        print(f"SDK payload: {report['sdk_payload']}; execution: requires run preflight")
        for issue in report["issues"]:
            print(f"- {issue}")
        for name, path in report["locations"].items():
            print(f"{name}: {json.dumps(path)}")
    return 3 if not report["execution_available"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
