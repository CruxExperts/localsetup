"""Bounded sandbox execution with separate authority to disclose captured output."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

from .sandbox import ProcessGrant, invocation
from .supervisor import Outcome, supervise


class _Cancellation:
    def __init__(self, revoked, cancel):
        self.revoked, self.cancel = revoked, cancel

    def is_set(self):
        return self.revoked.is_set() or (self.cancel is not None and self.cancel.is_set())


def run(runtimes: Path, grant: ProcessGrant, *, task: str, session: str, provider: bool = False, cancel=None) -> Outcome:
    """Run a broker-prepared snapshot; never mutate the original workspace.

    Output is untrusted text. This function does not render it, prepare snapshots,
    accept writeback, or replace session/operation journaling and resource gates.
    """
    grant.check(task, session)
    if type(provider) is not bool or (provider and not grant.disclose_output):
        raise PermissionError('Provider disclosure of process output requires explicit authority')
    cancellation = _Cancellation(grant.revoked, cancel)
    if cancellation.is_set():
        return Outcome('cancelled', None)
    with invocation(runtimes, grant, task=task, session=session) as launch:
        remaining = grant.expires - time.monotonic()
        if remaining <= 0:
            return Outcome('timed_out', None)
        outcome = supervise(list(launch.command), b'', cwd=launch.cwd,
                            environment=launch.environment, timeout=remaining,
                            cancel=cancellation, capture=True)
        # Authority can expire while the process exits or its final pipes drain.
        if cancellation.is_set():
            return Outcome('cancelled', outcome.returncode)
        if time.monotonic() >= grant.expires:
            return Outcome('timed_out', outcome.returncode)
        grant.check(task, session)
        return outcome


def run_recorded(runtimes: Path, grant: ProcessGrant, journal, *, snapshot_sha256: str,
                 task: str, session: str, provider: bool = False, cancel=None, checkpoint: str | None = None, tool_call: dict | None = None) -> Outcome:
    """Persist intent before dispatch and evidence after teardown; never retry."""
    grant.check(task, session)
    if journal.task != task or journal.session != session:
        raise PermissionError('Journal and process identities must match')
    if type(provider) is not bool or (provider and not grant.disclose_output):
        raise PermissionError('Provider disclosure of process output requires explicit authority')
    for exposed in (Path('/usr'), grant.staging.resolve(), runtimes.resolve()):
        if journal.root.resolve().is_relative_to(exposed) or exposed.is_relative_to(journal.root.resolve()):
            raise ValueError('Journal must be separate from staging, runtime and system trees')
    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    operation = journal.begin('process', {'argv_sha256': digest(grant.command),
                                         'snapshot_sha256': snapshot_sha256},
                              checkpoint=checkpoint, tool_call=tool_call, timeout=max(0, grant.expires-time.monotonic()))
    try:
        outcome = run(runtimes, grant, task=task, session=session, provider=provider, cancel=cancel)
    except BaseException as exc:
        journal.finish(operation, 'uncertain', evidence_sha256=digest({'exception_type': type(exc).__name__}),
                       timeout=max(0, grant.expires-time.monotonic()))
        raise
    journal.finish(operation, outcome.status, evidence_sha256=digest({
        'status': outcome.status, 'returncode': outcome.returncode, 'data': outcome.data}),
                   timeout=max(0, grant.expires-time.monotonic()))
    if _Cancellation(grant.revoked, cancel).is_set():
        return Outcome('cancelled', outcome.returncode)
    if time.monotonic() >= grant.expires:
        return Outcome('timed_out', outcome.returncode)
    grant.check(task, session)
    return outcome
