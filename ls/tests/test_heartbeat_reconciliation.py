import hashlib
from pathlib import Path
from types import SimpleNamespace
import time

import pytest

from ls.core.agent import heartbeat_reconciliation as recovery
from ls.tests.test_heartbeat_action import configured
from ls.tests.test_heartbeat_execution import runtime, policy, fake_dispatch, execution, store


def lost_result(runtime, monkeypatch, *, compact=False, fail=None, advance=False):
    plan, state = policy(runtime, compact=compact)
    calls = fake_dispatch(monkeypatch, runtime, fail=fail)
    if advance:
        from ls.core.agent.session_owner import SessionOwner
        original_save = SessionOwner.save_checkpoint
        def save(owner, messages, **kwargs):
            if kwargs['run_id'] == 'run':
                operation = owner._journal.begin('process', dict(argv_sha256='a'*64, snapshot_sha256='b'*64))
                owner._journal.finish(operation, 'completed', evidence_sha256='c'*64)
            return original_save(owner, messages, **kwargs)
        monkeypatch.setattr(SessionOwner, 'save_checkpoint', save)
    workspace, root, source, value = runtime
    original = store.append
    def lost(root, workspace, event, head, **kwargs):
        if event['type'] == 'result':
            raise OSError('lost accounting acknowledgement')
        return original(root, workspace, event, head, **kwargs)
    monkeypatch.setattr(store, 'append', lost)
    with pytest.raises(OSError):
        execution.execute(source, workspace, root, expected_binding=plan['binding'], expected_head=state['head'])
    monkeypatch.setattr(store, 'append', original)
    path = Path(value['state_root'])/'heartbeat'/plan['binding']/'result.json'
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return plan, store.inspect(root, workspace), path, digest, calls


@pytest.mark.parametrize('compact,fail', [(False,None),(True,None),(True,'compact'),(False,'run')])
def test_retained_result_reconciles_without_dispatch_or_refund(runtime, monkeypatch, compact, fail):
    plan, state, path, digest, calls = lost_result(runtime, monkeypatch, compact=compact, fail=fail)
    workspace, root, source, _ = runtime
    before_calls, raw = list(calls), path.read_bytes()
    from ls.core.agent.heartbeat_accounting_cli import execute
    result = execute(SimpleNamespace(accounting_action='reconcile', input=source, accounting_root=root,
        expected_binding=plan['binding'], expected_head=state['head'], result_sha256=digest), workspace)
    assert result['accounting']['summary']['charged'] == state['summary']['charged']
    assert result['accounting']['summary']['status'] == 'awaiting_controller_review'
    assert result['result'] == digest and path.read_bytes() == raw and calls == before_calls
    with pytest.raises(ValueError, match='unresolved'):
        recovery.reconcile(source, workspace, root, expected_binding=plan['binding'],
            expected_head=result['accounting']['head'], expected_result=digest)


@pytest.mark.parametrize('bad', ['missing','digest','grant','checkpoint','head','binding'])
def test_bad_evidence_stays_uncertain(runtime, monkeypatch, bad):
    plan, state, path, digest, calls = lost_result(runtime, monkeypatch)
    workspace, root, source, value = runtime
    if bad == 'missing':
        path.unlink()
    elif bad == 'grant':
        (path.parent/'grant.json').write_text('{}')
    elif bad == 'checkpoint':
        session = Path(value['state_root'])/'sessions'/hashlib.sha256(value['session'].encode()).hexdigest()
        (session/'checkpoints'/execution.LOCK_NAME).unlink()
    with pytest.raises((ValueError, OSError)):
        recovery.reconcile(source, workspace, root,
            expected_binding='f'*64 if bad == 'binding' else plan['binding'],
            expected_head='f'*64 if bad == 'head' else state['head'],
            expected_result='f'*64 if bad == 'digest' else digest)
    assert store.inspect(root, workspace) == state and calls == ['run']


def test_compaction_history_remains_evidence_after_coding_advances_journal(runtime, monkeypatch):
    plan, state, path, digest, calls = lost_result(runtime, monkeypatch, compact=True, advance=True)
    workspace, root, source, value = runtime
    with pytest.raises(PermissionError, match='stale'):
        execution._history(value, workspace, plan['profile_sha256'], time.monotonic()+5,
                           value['checkpoint'])
    result = recovery.reconcile(source, workspace, root, expected_binding=plan['binding'],
                                expected_head=state['head'], expected_result=digest)
    assert result['accounting']['summary']['status'] == 'awaiting_controller_review'
    assert result['accounting']['summary']['charged'] == state['summary']['charged']
    assert calls == ['compact', 'run']


@pytest.mark.parametrize('bad', ['outcome','schema','phase','protocol','checkpoint'])
def test_changed_completed_evidence_cannot_be_promoted(runtime, monkeypatch, bad):
    plan, state, path, digest, calls = lost_result(runtime, monkeypatch)
    workspace, root, source, _ = runtime
    evidence = store._parse(path.read_bytes())
    if bad == 'outcome': evidence['outcome'] = 'accepted'
    elif bad == 'schema': evidence['schema_version'] = True
    elif bad == 'phase': evidence['phases'] = []
    elif bad == 'protocol': evidence['phases'][0]['process']['protocol']['completed'] = False
    else: evidence['checkpoint'] = 'f'*64
    raw = store.files.encode(evidence)
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        recovery.reconcile(source, workspace, root, expected_binding=plan['binding'],
            expected_head=state['head'], expected_result=hashlib.sha256(raw).hexdigest())
    assert store.inspect(root, workspace) == state and calls == ['run']
