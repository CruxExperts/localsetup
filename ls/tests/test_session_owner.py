from dataclasses import replace
import hashlib
import os
from pathlib import Path
import threading
import time

import pytest

from ls.core.agent import session_owner
from ls.core.agent.operation_journal import Journal
from ls.core.agent.session_owner import lease
from ls.tests.test_agent_file_broker import broker


@pytest.fixture
def state(broker):
    path = broker.grant.root.parent / 'sessions'
    path.mkdir(mode=0o700)
    return path


def own(state, broker, **kwargs):
    defaults = dict(task='task', session='session', workspace=broker.grant.root, expires=time.monotonic()+5)
    return lease(state, **(defaults | kwargs))


def write(owner, broker):
    return owner.write(broker, 'src/a.txt', b'changed', expected_before=hashlib.sha256(b'original').hexdigest())


def test_exclusive_owner_stale_handle_and_durable_identity(state, broker):
    with own(state, broker) as owner:
        with pytest.raises(TimeoutError):
            with own(state, broker, expires=time.monotonic()+.02):
                pass
        operation = write(owner, broker)
        assert owner.inspect()[operation]['outcome'] == 'applied'
    with pytest.raises(PermissionError, match='closed'):
        owner.inspect()
    with own(state, broker) as resumed:
        assert resumed.inspect()[operation]['outcome'] == 'applied'
    with pytest.raises(PermissionError, match='identity'):
        with own(state, broker, task='other'):
            pass


def test_uncertain_recovery_blocks_write_until_observation(state, broker, monkeypatch):
    with own(state, broker) as owner:
        original = os.replace
        def fail(source, target, *args, **kwargs):
            if str(source).startswith('.lscli-write-'):
                raise OSError('before replacement')
            return original(source, target, *args, **kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(os, 'replace', fail)
            with pytest.raises(OSError):
                write(owner, broker)
        operation, = owner.inspect()
    with own(state, broker) as resumed:
        with pytest.raises(PermissionError, match='reconciliation'):
            write(resumed, broker)
        assert resumed.reconcile_file(broker, operation) == 'not_applied'
        completed = write(resumed, broker)
        assert resumed.inspect()[completed]['outcome'] == 'applied'


@pytest.mark.parametrize('failure', ['revoked', 'expired', 'thread'])
def test_live_authority_and_thread_binding(state, broker, failure):
    revoked = threading.Event()
    with own(state, broker, revoked=revoked) as owner:
        if failure == 'revoked':
            revoked.set()
        elif failure == 'expired':
            owner.expires = time.monotonic()-1
        if failure == 'thread':
            caught = []
            def other():
                try: write(owner, broker)
                except PermissionError: caught.append(True)
            thread = threading.Thread(target=other); thread.start(); thread.join()
            assert caught == [True]
        else:
            with pytest.raises(PermissionError): write(owner, broker)
    assert (broker.grant.root/'src/a.txt').read_bytes() == b'original'


def test_owner_revocation_reaches_active_file_grant(state, broker, monkeypatch):
    revoked = threading.Event()
    with own(state, broker, revoked=revoked) as owner:
        begin = owner._journal.begin
        def revoke(*args, **kwargs):
            operation = begin(*args, **kwargs)
            revoked.set()
            return operation
        monkeypatch.setattr(owner._journal, 'begin', revoke)
        with pytest.raises(PermissionError): write(owner, broker)
    assert (broker.grant.root/'src/a.txt').read_bytes() == b'original'
    with own(state, broker) as resumed:
        assert next(iter(resumed.inspect().values()))['outcome'] == 'uncertain'


def test_foreign_workspace_and_state_overlap_refused(state, broker):
    with pytest.raises(ValueError, match='separate'):
        with own(broker.grant.root, broker): pass
    with own(state, broker) as owner:
        other = broker.grant.root.parent/'other'; other.mkdir()
        with pytest.raises(PermissionError, match='workspace'):
            write(owner, type(broker)(replace(broker.grant, root=other), broker.lease_root))
        with pytest.raises(ValueError, match='separate'):
            write(owner, type(broker)(broker.grant, state))


def test_uncertain_process_is_not_automatically_reconciled(state, broker):
    with own(state, broker) as owner:
        operation = owner._journal.begin('process', {'argv_sha256':'a'*64, 'snapshot_sha256':'b'*64})
    with own(state, broker) as resumed:
        with pytest.raises(ValueError, match='file operation'):
            resumed.reconcile_file(broker, operation)
        with pytest.raises(PermissionError, match='reconciliation'):
            write(resumed, broker)
        assert resumed.inspect()[operation]['outcome'] == 'uncertain'


def test_process_dispatch_caps_authority_and_rejects_reentry(state, broker, monkeypatch):
    from ls.core.agent.sandbox import ProcessGrant
    stage = broker.grant.root.parent/'stage'; stage.mkdir(mode=0o700)
    grant = ProcessGrant('task', 'session', stage, ('/usr/bin/true',), time.monotonic()+100)
    revoked = threading.Event()
    with own(state, broker, revoked=revoked) as owner:
        def run(runtimes, bound, journal, **kwargs):
            assert bound.expires == owner.expires
            assert not bound.revoked.is_set()
            with pytest.raises(PermissionError, match='already active'):
                owner.inspect()
            revoked.set()
            assert bound.revoked.is_set()
            return 'fixture'
        monkeypatch.setattr(session_owner, 'run_recorded', run)
        assert owner.run(Path('/tmp/runtime-fixture'), grant, snapshot_sha256='a'*64) == 'fixture'
