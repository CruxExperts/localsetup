"""Explicit action selection on the existing opt-in heartbeat run command."""
import json
import os
from pathlib import Path
import stat
import threading
import time

from .profile_setup import _parent
from .registration_owner import _read
from .run_io import Streams

FIELDS = ('action_input', 'accounting_root', 'expected_binding', 'expected_head')


def arguments(parser):
    parser.add_argument('--action-input', type=Path, help='Explicit private heartbeat action JSON')
    parser.add_argument('--accounting-root', type=Path)
    parser.add_argument('--expected-binding')
    parser.add_argument('--expected-head')


def selected(args):
    return any(getattr(args, field, None) is not None for field in FIELDS)


def _config(path):
    parent = _parent(path, create=False)
    if parent is None:
        return {}
    try:
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        except FileNotFoundError:
            return {}
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_mode & 0o022:
                raise ValueError('Heartbeat configuration must be an owned regular file')
            raw = os.read(fd, 65537)
            if len(raw) > 65536:
                raise ValueError('Heartbeat configuration exceeds 64 KiB')
        finally:
            os.close(fd)
    finally:
        os.close(parent)
    import yaml
    value = yaml.safe_load(raw)
    if not isinstance(value, dict):
        raise ValueError('Heartbeat configuration must be an object')
    return value


def execute(args, workspace, framework):
    if args.no_agent:
        return {'schema_version': 1, 'outcome': 'skipped', 'reason': 'no_agent'}, 0
    config_path = workspace/'config/codex_heartbeat.yaml'
    config = _config(config_path)
    heartbeat = config.get('heartbeat', {})
    if not isinstance(heartbeat, dict) or type(heartbeat.get('enabled', False)) is not bool:
        raise ValueError('Heartbeat enabled must be a boolean')
    if not heartbeat.get('enabled', False) and not args.force:
        return {'schema_version': 1, 'outcome': 'skipped', 'reason': 'heartbeat.disabled'}, 0
    if 'state_dir' in heartbeat and (not isinstance(heartbeat['state_dir'], str) or len(heartbeat['state_dir']) > 4096):
        raise ValueError('Heartbeat state directory must be a bounded relative string')
    if any(getattr(args, field, None) is None for field in FIELDS):
        raise ValueError('Action dispatch requires all four explicit controller options')
    from ..harness import _load_runtime
    runtime = _load_runtime(framework)
    state = runtime.state_root_from_config(workspace, config)
    # Preserve the existing overlap protocol, but refuse unsafe lock inputs.
    fd = _parent(state/runtime.LOCK_NAME, create=True)
    try:
        _read(fd, runtime.LOCK_NAME)
    finally:
        os.close(fd)
    lock, _ = runtime.acquire_lock(state, runtime.stale_after_seconds(config))
    if lock is None:
        return {'schema_version': 1, 'outcome': 'locked'}, 1
    try:
        from .heartbeat_execution import execute as dispatch
        result = dispatch(args.action_input, workspace, args.accounting_root,
                          expected_binding=args.expected_binding, expected_head=args.expected_head,
                          control_paths=(config_path, state))
    finally:
        runtime.release_lock(state, lock)
    codes = {'execution_completed': 0, 'cancelled': 130, 'timed_out': 124, 'output_limit': 5, 'failed': 1}
    return result, codes.get(result['outcome'], 1)


def main(args, workspace, framework):
    try:
        result, code = execute(args, workspace, framework)
        Streams(time.monotonic()+5, threading.Event()).write(json.dumps(result, ensure_ascii=True)+'\n')
        return code
    except KeyboardInterrupt:
        return 130
    except Exception:
        try:
            Streams(time.monotonic()+5, threading.Event(), output_fd=2).write(
                'Heartbeat action unavailable; inspect configuration, controller inputs and retained execution evidence before retrying.\n')
        except (OSError, ValueError, TimeoutError):
            pass
        return 2
