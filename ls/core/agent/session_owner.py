"""Exclusive live session ownership and recovery-gated broker dispatch."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path
import threading
import time

from .file_broker import FileBroker
from .file_recovery import reconcile, root_digest
from .operation_journal import IDENTIFIER, Journal
from .process_broker import run_recorded
from .runtime_install import _write_json
from .runtime_lock import _directory, runtime_use


class _Revocation:
    def __init__(self, *events):
        self.events = events

    def is_set(self):
        return any(event.is_set() for event in self.events)


def _separate(left, right):
    left, right = left.resolve(), right.resolve()
    if left.is_relative_to(right) or right.is_relative_to(left):
        raise ValueError('Session state must be separate from execution and target trees')


def _private(root):
    fd = _directory(root)
    if os.fstat(fd).st_mode & 0o077:
        os.close(fd)
        raise ValueError('Session state must be private')
    return fd


class SessionOwner:
    """Created only by lease(); persisted identity does not confer authority."""
    def __init__(self, root, journal, identity, expires, revoked):
        self.root, self._journal, self._identity = root, journal, identity
        self.expires, self._closed = expires, threading.Event()
        self.revoked = _Revocation(revoked, self._closed)
        self._thread, self._busy = threading.get_ident(), threading.Lock()

    def _check(self):
        if threading.get_ident() != self._thread or self.revoked.is_set() or time.monotonic() >= self.expires:
            raise PermissionError('Session owner is closed, revoked, expired or on another thread')

    @contextmanager
    def _operation(self, *, recovery=False):
        self._check()
        if not self._busy.acquire(blocking=False):
            raise PermissionError('Session dispatch is already active')
        try:
            states = self._journal.inspect(timeout=max(0, self.expires-time.monotonic()))
            self._check()
            if not recovery and any(state['outcome'] == 'uncertain' for state in states.values()):
                raise PermissionError('Session requires reconciliation before dispatch')
            yield states
        finally:
            self._busy.release()

    def inspect(self):
        with self._operation(recovery=True) as states:
            return states

    def _broker(self, broker):
        grant = broker.grant
        if (grant.task, grant.session) != (self._journal.task, self._journal.session):
            raise PermissionError('File grant does not belong to this session task')
        if root_digest(grant.root) != self._identity['workspace_sha256']:
            raise PermissionError('File grant workspace identity differs from session')
        _separate(self.root.parent, broker.lease_root)
        return FileBroker(replace(grant, expires=min(grant.expires, self.expires),
                                  revoked=_Revocation(grant.revoked, self.revoked)), broker.lease_root)

    def write(self, broker, name, data, *, expected_before):
        with self._operation():
            bound = self._broker(broker)
            return bound.write_recorded(self._journal.task, self._journal.session, name, data,
                                        expected_before=expected_before, journal=self._journal)

    def reconcile_file(self, broker, operation):
        with self._operation(recovery=True):
            return reconcile(self._broker(broker), self._journal, operation,
                             task=self._journal.task, session=self._journal.session)

    def run(self, runtimes, grant, *, snapshot_sha256, provider=False, cancel=None):
        with self._operation():
            for boundary in (runtimes, grant.staging, Path('/usr')):
                _separate(self.root.parent, boundary)
            bound = replace(grant, expires=min(grant.expires, self.expires),
                            revoked=_Revocation(grant.revoked, self.revoked))
            return run_recorded(runtimes, bound, self._journal, snapshot_sha256=snapshot_sha256,
                                task=self._journal.task, session=self._journal.session,
                                provider=provider, cancel=cancel)


@contextmanager
def lease(state: Path, *, task: str, session: str, workspace: Path, expires: float, revoked=None):
    """Own a canonical session until context exit; acquire before child leases."""
    if any(not isinstance(value, str) or not IDENTIFIER.fullmatch(value) for value in (task, session)):
        raise ValueError('Session requires bounded task and session identifiers')
    if not math.isfinite(expires) or expires <= time.monotonic():
        raise PermissionError('Session requires a live finite deadline')
    revoked = revoked if revoked is not None else threading.Event()
    if revoked.is_set():
        raise PermissionError('Session is revoked')
    state = state.absolute()
    _separate(state, workspace)
    name = hashlib.sha256(session.encode()).hexdigest()
    fd = _private(state)
    try:
        try:
            os.mkdir(name, mode=0o700, dir_fd=fd)
            os.fsync(fd)
        except FileExistsError:
            pass
    finally:
        os.close(fd)
    root = state / name
    identity = {'schema_version': 1, 'task': task, 'session': session,
                'workspace_sha256': root_digest(workspace)}
    with runtime_use(root, exclusive=True, timeout=max(0, expires-time.monotonic())):
        fd = _private(root)
        try:
            if revoked.is_set() or time.monotonic() >= expires:
                raise PermissionError('Session authority ended while acquiring its lease')
            record = root / 'identity.json'
            if record.exists() or record.is_symlink():
                record_fd = os.open('identity.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                try:
                    import stat
                    info = os.fstat(record_fd)
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or info.st_mode & 0o7077:
                        raise ValueError('Session identity must be a private regular file')
                    raw = os.read(record_fd, 16385)
                    if len(raw) > 16384 or json.loads(raw) != identity:
                        raise PermissionError('Stored session identity does not match this task and workspace')
                finally:
                    os.close(record_fd)
            else:
                _write_json(record, identity)
            try:
                os.mkdir('journal', mode=0o700, dir_fd=fd)
                os.fsync(fd)
            except FileExistsError:
                pass
        finally:
            os.close(fd)
        owner = SessionOwner(root, Journal(root/'journal', task=task, session=session), identity, expires, revoked)
        try:
            owner.inspect()
            yield owner
        finally:
            owner._closed.set()
