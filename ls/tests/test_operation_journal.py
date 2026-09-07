import hashlib
import json
import os

import pytest

from ls.core.agent import operation_journal as journal

H = hashlib.sha256(b'evidence').hexdigest()
REQUEST = {'path': 'src/main.py', 'before': None, 'after': H}


@pytest.fixture
def log(tmp_path):
    tmp_path.chmod(0o700)
    return journal.Journal(tmp_path, task='task', session='session')


def test_intent_outcome_chain_and_terminal_immutability(log):
    operation = log.begin('file_replace', REQUEST, checkpoint=H)
    assert log.inspect()[operation]['outcome'] == 'uncertain'
    with pytest.raises(ValueError, match='Unreconciled'):
        log.begin('process', {'argv_sha256': H, 'snapshot_sha256': H})
    log.finish(operation, 'applied', evidence_sha256=H)
    state = log.inspect()[operation]
    assert state['outcome'] == 'applied' and not state['result']['reconciled']
    records = sorted(log.root.glob('*.json'))
    assert json.loads(records[1].read_text())['previous'] == hashlib.sha256(records[0].read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='transition'):
        log.finish(operation, 'not_applied', evidence_sha256=H, reconciled=True)
    log.begin('process', {'argv_sha256': H, 'snapshot_sha256': H})


def test_restart_requires_explicit_reconciliation(log):
    operation = log.begin('file_replace', REQUEST)
    recovered = journal.Journal(log.root, task='task', session='session')
    with pytest.raises(PermissionError, match='reconciliation'):
        recovered.finish(operation, 'applied', evidence_sha256=H)
    with pytest.raises(ValueError, match='Unreconciled'):
        recovered.begin('file_replace', REQUEST)
    recovered.finish(operation, 'not_applied', evidence_sha256=H, reconciled=True)
    assert recovered.inspect()[operation]['result']['reconciled']
    recovered.begin('file_replace', REQUEST)


def test_uncertain_result_requires_reconciliation_even_same_owner(log):
    operation = log.begin('file_replace', REQUEST)
    log.finish(operation, 'uncertain', evidence_sha256=H)
    with pytest.raises(PermissionError):
        log.finish(operation, 'applied', evidence_sha256=H)
    log.finish(operation, 'applied', evidence_sha256=H, reconciled=True)


@pytest.mark.parametrize('damage', ['content', 'gap', 'symlink', 'hardlink', 'mode', 'schema'])
def test_corruption_refuses_recovery_and_dispatch(log, damage):
    log.begin('file_replace', REQUEST)
    path = log.root / '00000000.json'
    if damage == 'content':
        path.write_bytes(path.read_bytes()+b' ')
    elif damage == 'gap':
        path.rename(log.root / '00000002.json')
    elif damage == 'symlink':
        path.rename(log.root / 'outside');path.symlink_to('outside')
    elif damage == 'hardlink':
        os.link(path, log.root / 'extra')
    elif damage == 'mode':
        path.chmod(0o644)
    else:
        value=json.loads(path.read_text());value['extra']='unexpected';path.write_bytes(journal._encode(value))
    with pytest.raises((ValueError, OSError)):
        log.inspect()
    with pytest.raises((ValueError, OSError)):
        log.begin('file_replace', REQUEST)


def test_interrupted_temporary_record_never_authorizes_dispatch(log, monkeypatch):
    original = journal.os.rename
    monkeypatch.setattr(journal.os, 'rename', lambda *args, **kwargs: (_ for _ in ()).throw(OSError('fixture interruption')))
    with pytest.raises(OSError):
        log.begin('file_replace', REQUEST)
    assert log.inspect() == {}
    assert list(log.root.glob('.pending-*'))
    monkeypatch.setattr(journal.os, 'rename', original)
    assert log.begin('file_replace', REQUEST)


def test_identity_and_request_schema_are_bound(log):
    operation = log.begin('file_replace', REQUEST)
    with pytest.raises(ValueError, match='identity'):
        journal.Journal(log.root, task='other', session='session').inspect()
    with pytest.raises(ValueError, match='file replacement'):
        log.finish(operation, 'completed', evidence_sha256=H)
    assert log.inspect()[operation]['outcome']=='uncertain'


def test_record_limit_fails_closed(log, monkeypatch):
    operation = log.begin('file_replace', REQUEST)
    monkeypatch.setattr(journal, 'MAX_RECORDS', 1)
    with pytest.raises(ValueError, match='full'):
        log.finish(operation, 'applied', evidence_sha256=H)
    assert log.inspect()[operation]['outcome']=='uncertain'


def test_recorded_process_joins_intent_and_result(log, tmp_path, monkeypatch):
    import time
    from ls.core.agent import process_broker
    from ls.core.agent.sandbox import ProcessGrant
    staging = tmp_path.parent / (tmp_path.name+'-staging')
    runtime = tmp_path.parent / (tmp_path.name+'-runtime')
    grant = ProcessGrant('task', 'session', staging, ('/usr/bin/true',), time.monotonic()+2)
    def run(*args, **kwargs):
        state, = log.inspect().values()
        assert state['outcome']=='uncertain' and state['intent']['kind']=='process'
        return process_broker.Outcome('completed', 0, {'stdout':'fixture','stderr':''})
    monkeypatch.setattr(process_broker, 'run', run)
    result=process_broker.run_recorded(runtime,grant,log,snapshot_sha256=H,task='task',session='session')
    assert result.status=='completed'
    state, = log.inspect().values()
    assert state['outcome']=='completed'
    assert 'fixture' not in ''.join(p.read_text() for p in log.root.glob('*.json'))


def test_recorded_process_exception_retains_uncertain_operation(log, tmp_path, monkeypatch):
    import time
    from ls.core.agent import process_broker
    from ls.core.agent.sandbox import ProcessGrant
    grant=ProcessGrant('task','session',tmp_path.parent/(tmp_path.name+'-stage'),('/usr/bin/true',),time.monotonic()+2)
    def fail(*args, **kwargs):
        raise OSError('private diagnostic')
    monkeypatch.setattr(process_broker,'run',fail)
    with pytest.raises(OSError):
        process_broker.run_recorded(tmp_path.parent/(tmp_path.name+'-runtime'),grant,log,snapshot_sha256=H,task='task',session='session')
    state,=log.inspect().values()
    assert state['outcome']=='uncertain'
    assert 'private diagnostic' not in ''.join(p.read_text() for p in log.root.glob('*.json'))
    with pytest.raises(ValueError,match='Unreconciled'):
        log.begin('file_replace',REQUEST)


@pytest.mark.parametrize('action', ['revoke', 'expire', 'cancel'])
def test_authority_loss_during_outcome_append_suppresses_output(log, tmp_path, monkeypatch, action):
    import threading
    import time
    from ls.core.agent import process_broker
    from ls.core.agent.sandbox import ProcessGrant
    grant=ProcessGrant('task','session',tmp_path.parent/(tmp_path.name+'-stage'),('/usr/bin/true',),time.monotonic()+2)
    cancel=threading.Event()
    monkeypatch.setattr(process_broker,'run',lambda *args,**kwargs: process_broker.Outcome('completed',0,{'stdout':'private','stderr':''}))
    original=log.finish
    def finish(*args, **kwargs):
        original(*args, **kwargs)
        if action=='revoke':grant.revoked.set()
        elif action=='cancel':cancel.set()
        else:monkeypatch.setattr(process_broker.time,'monotonic',lambda:grant.expires+1)
    monkeypatch.setattr(log,'finish',finish)
    result=process_broker.run_recorded(tmp_path.parent/(tmp_path.name+'-runtime'),grant,log,snapshot_sha256=H,task='task',session='session',cancel=cancel)
    assert result.data is None and result.status==('timed_out' if action=='expire' else 'cancelled')
    assert next(iter(log.inspect().values()))['outcome']=='completed'


def test_intent_reserves_capacity_for_terminal_evidence(log, monkeypatch):
    monkeypatch.setattr(journal,'MAX_RECORDS',1)
    with pytest.raises(ValueError,match='full'):
        log.begin('file_replace',REQUEST)
    assert log.inspect()=={}
    monkeypatch.setattr(journal,'MAX_RECORDS',2)
    operation=log.begin('file_replace',REQUEST)
    with pytest.raises(ValueError,match='full'):
        log.finish(operation,'uncertain',evidence_sha256=H)
    log.finish(operation,'not_applied',evidence_sha256=H)
    assert log.inspect()[operation]['outcome']=='not_applied'


def test_recovery_suffix_requires_exact_settled_prefix(log):
    empty = log.frontier()
    first = log.begin('file_replace', REQUEST)
    uncertain = log.frontier()
    log.finish(first, 'applied', evidence_sha256=H)
    settled = log.frontier()
    second = log.begin('file_replace', REQUEST)
    log.finish(second, 'not_applied', evidence_sha256=H)
    assert list(log.after(empty)['operations']) == [first, second]
    assert list(log.after(settled)['operations']) == [second]
    assert log.after(settled)['frontier'] == log.frontier()
    assert log.after(log.frontier())['operations'] == {}
    with pytest.raises(PermissionError, match='uncertain'):
        log.after(uncertain)
    with pytest.raises(PermissionError, match='not in this journal'):
        log.after('f'*64)
