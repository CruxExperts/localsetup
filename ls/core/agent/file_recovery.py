"""Read-only target reconciliation under fresh authority; no mutation replay."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time

from .file_broker import parent, _regular, digest_descriptor, properties_digest


def root_digest(root: Path) -> str:
    with parent(root, ('identity',)) as (fd, _):
        info = os.fstat(fd)
        value = {'path': str(root.resolve()), 'device': info.st_dev, 'inode': info.st_ino}
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def journal_binding(broker, journal, task, session):
    if journal.task != task or journal.session != session:
        raise PermissionError('Journal and file operation identities must match')
    for boundary in (broker.grant.root.resolve(), broker.lease_root.resolve()):
        if journal.root.resolve().is_relative_to(boundary) or boundary.is_relative_to(journal.root.resolve()):
            raise ValueError('Journal must be separate from workspace and target lease state')


def reconcile(broker, journal, operation: str, *, task: str, session: str) -> str:
    journal_binding(broker, journal, task, session)
    state = journal.inspect(timeout=max(0, broker.grant.expires-time.monotonic())).get(operation)
    if state is None or state['intent']['kind'] != 'file_replace' or state['outcome'] != 'uncertain':
        raise ValueError('Reconciliation requires an unfinished file operation')
    request = state['intent']['request']
    name = request['path']
    broker.grant.check(task, session, 'read', name)
    if request.get('root_sha256') != root_digest(broker.grant.root) or 'after_properties' not in request:
        raise PermissionError('File operation has no matching workspace identity')
    with broker._target(task, session, 'read', name) as (directory, leaf):
        if request['root_sha256'] != root_digest(broker.grant.root):
            raise PermissionError('Workspace identity changed during reconciliation')
        try:
            fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        except FileNotFoundError:
            observed, properties, info = None, None, None
        else:
            try:
                info = os.fstat(fd)
                _regular(info)
                observed = digest_descriptor(fd, info)
                properties = properties_digest(fd)
                final = os.fstat(fd)
                if (info.st_mtime_ns, info.st_ctime_ns) != (final.st_mtime_ns, final.st_ctime_ns):
                    raise PermissionError('File properties changed during reconciliation')
            finally:
                os.close(fd)
        broker.grant.check(task, session, 'read', name)
        if observed == request['after'] and properties == request['after_properties']:
            outcome = 'applied'
        elif observed == request['before'] and properties == request['before_properties']:
            outcome = 'not_applied'
        else:
            raise PermissionError('Current file conflicts with both recorded states; manual reconciliation required')
        evidence = hashlib.sha256(json.dumps({'operation': operation, 'observed': observed, 'properties': properties,
            'root_sha256': request['root_sha256']}, sort_keys=True).encode()).hexdigest()
        if request['root_sha256'] != root_digest(broker.grant.root):
            raise PermissionError('Workspace identity changed during reconciliation')
        with parent(broker.grant.root, tuple(Path(name).parts)) as (current_parent, _):
            held, current = os.fstat(directory), os.fstat(current_parent)
            if (held.st_dev, held.st_ino) != (current.st_dev, current.st_ino):
                raise PermissionError('Parent identity changed during reconciliation')
        try:
            current = os.stat(leaf, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            current = None
        identity = lambda value: None if value is None else (
            value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        if identity(info) != identity(current):
            raise PermissionError('File identity changed during reconciliation')
        broker.grant.check(task, session, 'read', name)
        journal.finish(operation, outcome, evidence_sha256=evidence, reconciled=True,
                       timeout=max(0, broker.grant.expires-time.monotonic()))
        return outcome
