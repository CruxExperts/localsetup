"""Controller-only accounting commands; never dispatch agent work."""
import hashlib
import json
import os
from pathlib import Path
import threading
import time

from . import heartbeat_budget_store as store
from .profile_setup import _parent, _target
from .session_owner import _separate
from .run_io import Streams


def arguments(parent, target_flags):
    parser = parent.add_parser("accounting")
    sub = parser.add_subparsers(dest="accounting_action", required=True)
    for action in ("init", "inspect", "review", "action-plan"):
        item = sub.add_parser(action)
        target_flags(item)
        item.add_argument("--accounting-root", type=Path, required=True)
        if action != "inspect":
            item.add_argument("--input", type=Path, required=True)
        if action == "init":
            mode = item.add_mutually_exclusive_group(required=True)
            mode.add_argument("--plan", action="store_true")
            mode.add_argument("--apply", action="store_true")
            item.add_argument("--policy-sha256")
        elif action == "review":
            item.add_argument("--expected-head", required=True)


def _input(path, workspace):
    path = _target(path)
    _separate(path, workspace)
    fd = _parent(path, create=False)
    if fd is None:
        raise FileNotFoundError("Controller input is missing")
    try:
        raw = store.files._read(fd, path.name)
    finally:
        os.close(fd)
    if raw is None:
        raise FileNotFoundError("Controller input is missing")
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("Duplicate controller input field")
            value[key] = item
        return value
    return json.loads(raw, object_pairs_hook=pairs)


def report(root, workspace):
    return {"schema_version": 1, **store.inspect(root, workspace),
            "financial_estimate": {"status": "unavailable", "reason": "No pricing input supplied"}}


def execute(args, workspace):
    workspace = _target(workspace)
    if args.accounting_action == "inspect":
        return report(args.accounting_root, workspace)
    if args.accounting_action == "action-plan":
        from .heartbeat_action import plan
        return plan(args.input, workspace, args.accounting_root)
    value = _input(args.input, workspace)
    if args.accounting_action == "review":
        store.budget._keys(value, {"operation", "result", "decision", "evidence", "rationale"})
        event = {"type": "review", **value}
        return {"schema_version": 1, **store.append(args.accounting_root, workspace, event, args.expected_head)}
    root, workspace = store._paths(args.accounting_root, workspace)
    raw = store.files.encode(store._document(value, workspace))
    digest = hashlib.sha256(raw).hexdigest()
    if args.plan:
        if args.policy_sha256 is not None:
            raise ValueError("Plan does not accept an apply digest")
        fd = _parent(root / store.POLICY, create=False)
        if fd is not None:
            try:
                if store._names(fd) - {store.LOCK_NAME}:
                    raise FileExistsError("Accounting target exists")
            finally:
                os.close(fd)
        return {"schema_version": 1, "operation": "initialize_accounting",
                "root": str(root), "workspace": str(workspace), "sha256": digest}
    if not args.policy_sha256:
        raise ValueError("Apply requires the reviewed policy digest")
    return {"schema_version": 1, **store.initialize(root, workspace, value, args.policy_sha256)}


def main(args, workspace):
    try:
        result = execute(args, workspace)
        Streams(time.monotonic()+5, threading.Event()).write(json.dumps(result, ensure_ascii=True)+"\n")
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, TypeError, RuntimeError, RecursionError, KeyError):
        try:
            Streams(time.monotonic()+5, threading.Event(), output_fd=2).write(
                "Heartbeat accounting unavailable; inspect the private input, workspace, policy digest and current head.\n")
        except (OSError, ValueError, TimeoutError):
            pass
        return 2
