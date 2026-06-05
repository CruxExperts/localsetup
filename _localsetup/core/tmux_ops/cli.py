from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from .constants import DEFAULT_RUN_TIMEOUT, DEFAULT_TAIL_LINES, DEFAULT_WAIT_TIMEOUT
from .legacy import cmd_send, cmd_wait
from .run_control import _command_from_remainder, cmd_cancel, cmd_run, cmd_status
from .sanitize import _compile_idle_re
from .session import cmd_pick, cmd_probe


def _emit_error(out: dict[str, Any]) -> None:
    err = out.get("error", "unknown error")
    detail = out.get("detail", "")
    source = out.get("source", "")
    parts = [f"tmux_ops: {err}"]
    if detail:
        parts.append(f" detail={detail}")
    if source:
        parts.append(f" source={source}")
    sys.stderr.write("".join(parts) + "\n")


def main() -> int:
    try:
        parser = argparse.ArgumentParser(description="Managed tmux ops: pick, probe, run, status, cancel.")
        subparsers = parser.add_subparsers(dest="command", required=True)

        subparsers.add_parser("pick", help="Pick or create the first safe managed ops session")

        probe_p = subparsers.add_parser("probe", help="Check sudo readiness without fixed sleeps")
        probe_p.add_argument("-t", "--target", required=True, metavar="SESSION")

        run_p = subparsers.add_parser("run", help="Run a command in a managed tmux session")
        run_p.add_argument("-t", "--target", required=True, metavar="SESSION")
        run_p.add_argument("--timeout", type=float, default=DEFAULT_RUN_TIMEOUT, metavar="SECS")
        run_p.add_argument("--tail", type=int, default=DEFAULT_TAIL_LINES, metavar="N")
        run_p.add_argument("cmd", nargs=argparse.REMAINDER, metavar="-- CMD")

        status_p = subparsers.add_parser("status", help="Report active or completed run status")
        status_p.add_argument("-t", "--target", required=True, metavar="SESSION")
        status_p.add_argument("--run-id", default=None, metavar="ID")
        status_p.add_argument("--wait", action="store_true", default=False)
        status_p.add_argument("--timeout", type=float, default=DEFAULT_WAIT_TIMEOUT, metavar="SECS")
        status_p.add_argument("--tail", type=int, default=DEFAULT_TAIL_LINES, metavar="N")

        cancel_p = subparsers.add_parser("cancel", help="Interrupt the active managed run")
        cancel_p.add_argument("-t", "--target", required=True, metavar="SESSION")
        cancel_p.add_argument("--run-id", required=True, metavar="ID")

        send_p = subparsers.add_parser("send", help="Legacy: send one command to pane")
        send_p.add_argument("-t", "--target", required=True, metavar="SESSION")
        send_p.add_argument("-d", "--delay", type=float, default=None, metavar="SECS")
        send_p.add_argument("--wait", action="store_true", default=False)
        send_p.add_argument("--wait-timeout", type=float, default=DEFAULT_WAIT_TIMEOUT, metavar="SECS")
        send_p.add_argument("--idle-re", default=None, metavar="PATTERN")
        send_p.add_argument("cmd", nargs=1, metavar="CMD")

        wait_p = subparsers.add_parser("wait", help="Legacy: poll pane until prompt idle or timeout")
        wait_p.add_argument("-t", "--target", required=True, metavar="SESSION")
        wait_p.add_argument("--timeout", type=float, default=DEFAULT_WAIT_TIMEOUT, metavar="SECS")
        wait_p.add_argument("--idle-re", default=None, metavar="PATTERN")
        wait_p.add_argument("--pre-cursor-y", type=int, default=None, metavar="N")

        args = parser.parse_args()

        if args.command == "pick":
            out = cmd_pick()
        elif args.command == "probe":
            out = cmd_probe(args.target)
        elif args.command == "run":
            cmd, cmd_err = _command_from_remainder(args.cmd)
            out = (
                {"error": "invalid command", "detail": cmd_err, "source": "run"}
                if cmd_err
                else cmd_run(args.target, cmd or "", args.timeout, args.tail)
            )
        elif args.command == "status":
            out = cmd_status(args.target, args.run_id, args.wait, args.timeout, args.tail)
        elif args.command == "cancel":
            out = cmd_cancel(args.target, args.run_id)
        elif args.command == "send":
            idle_re, re_err = _compile_idle_re(args.idle_re)
            out = (
                {"error": "invalid --idle-re pattern", "detail": re_err, "source": "send"}
                if re_err
                else cmd_send(
                    args.target,
                    args.cmd[0],
                    args.delay,
                    wait=args.wait,
                    wait_timeout=args.wait_timeout,
                    idle_re=idle_re,
                )
            )
        elif args.command == "wait":
            idle_re, re_err = _compile_idle_re(args.idle_re)
            out = (
                {"error": "invalid --idle-re pattern", "detail": re_err, "source": "wait"}
                if re_err
                else cmd_wait(
                    args.target,
                    timeout=args.timeout,
                    idle_re=idle_re,
                    pre_cursor_y=args.pre_cursor_y,
                )
            )
        else:
            out = {"error": "unknown command", "source": "main"}

        if "error" in out:
            _emit_error(out)
        print(json.dumps(out))
        return 0 if "error" not in out else 1
    except Exception as e:
        err_payload = {
            "error": "unexpected exception",
            "exception_type": type(e).__name__,
            "exception_message": str(e),
            "source": "main",
        }
        _emit_error(err_payload)
        print(json.dumps(err_payload))
        if os.environ.get("LOCALSETUP_DEBUG"):
            import traceback

            sys.stderr.write(traceback.format_exc())
        return 1
