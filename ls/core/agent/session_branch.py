"""Explicit compatible history branching; never copies operation authority."""
from __future__ import annotations

import json
from pathlib import Path
import threading
import time
import uuid

from .profiles import load, wire
from .session_owner import lease


def branch(state, *, source_task, source_session, checkpoint, task, session,
           workspace, profile, expires, revoked=None):
    if source_session == session:
        raise ValueError('Branch requires a different destination session')
    with lease(state, task=source_task, session=source_session, workspace=workspace,
               expires=expires, revoked=revoked, create=False) as source:
        messages = source.resume_checkpoint(checkpoint, profile=profile)
        # Existing targets are refused before locking. A raced lock acquisition
        # fails immediately, so nested source/destination leases cannot deadlock.
        with lease(state, task=task, session=session, workspace=workspace,
                   expires=expires, revoked=revoked, new=True) as destination:
            if destination.inspect():
                raise PermissionError('Branch destination must have no operations')
            source.resume_checkpoint(checkpoint, profile=profile)
            result = destination.save_checkpoint(messages, profile=profile,
                run_id=uuid.uuid4().hex, step=0, state='complete')
            receipt = {'schema_version': 1, 'mode': 'native',
                'source_task': source_task, 'source_session': source_session,
                'source_checkpoint': checkpoint, 'task': task, 'session': session,
                'checkpoint': result, 'profile': profile}
            from .runtime_install import _write_json
            _write_json(destination.root/'branch.json', receipt)
            source.resume_checkpoint(checkpoint, profile=profile)
            if destination.resume_checkpoint(result, profile=profile) != messages:
                raise ValueError('Branched history differs from source')
            return receipt


def arguments(parser):
    for name in ('source-task', 'source-session', 'checkpoint', 'task', 'session', 'profile'):
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--workspace', type=Path, default=Path.cwd())
    parser.add_argument('--state-root', type=Path)
    parser.add_argument('--profiles', type=Path)
    parser.add_argument('--timeout', type=float, default=30)


def main(args):
    from .coding_protocol import profile_digest
    from .diagnostics import locations
    from .run_cli import failure
    from .run_io import Streams
    import math
    try:
        if not math.isfinite(args.timeout) or not 0 < args.timeout <= 300:
            raise ValueError('Branch timeout must be within 300 seconds')
        defaults = locations(Path.home())
        state = (args.state_root or Path(defaults['state'])).absolute()
        profile = load(args.profiles or Path(defaults['profiles']), args.profile)
        result = branch(state/'sessions', source_task=args.source_task,
            source_session=args.source_session, checkpoint=args.checkpoint,
            task=args.task, session=args.session, workspace=args.workspace.absolute(),
            profile=profile_digest(wire(profile)), expires=time.monotonic()+args.timeout)
        Streams(time.monotonic()+1, threading.Event()).write(json.dumps(result, ensure_ascii=True)+'\n')
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, TypeError, RecursionError, RuntimeError):
        return failure('text', 0, 'failed', 2,
            'branch failed; inspect destination evidence before retrying with a new session.')
