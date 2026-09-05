"""Bounded sandbox execution with separate authority to disclose captured output."""
from __future__ import annotations

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
