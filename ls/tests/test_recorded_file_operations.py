from dataclasses import replace
import hashlib
import os
from pathlib import Path

import pytest

from ls.core.agent.file_broker import FileBroker
from ls.core.agent.file_recovery import reconcile
from ls.core.agent.operation_journal import Journal
from ls.core.agent.runtime_lock import runtime_use
from ls.tests.test_agent_file_broker import broker


def digest(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def log(broker):
    root=broker.grant.root.parent/'journal';root.mkdir(mode=0o700)
    return Journal(root,task='task',session='session')


def write(broker,log,expected=digest(b'original')):
    return broker.write_recorded('task','session','src/a.txt',b'changed',expected_before=expected,journal=log)


def test_recorded_write_holds_target_lease_and_records_preconditions(broker,log,monkeypatch):
    original=log.begin
    def begin(*args,**kwargs):
        with pytest.raises(TimeoutError):
            with runtime_use(broker.lease_root,exclusive=True,timeout=0):pass
        return original(*args,**kwargs)
    monkeypatch.setattr(log,'begin',begin)
    operation=write(broker,log)
    state=log.inspect()[operation]
    assert state['outcome']=='applied'
    assert state['intent']['request']['before']==digest(b'original')
    assert state['intent']['request']['after']==digest(b'changed')
    assert len(state['intent']['request']['root_sha256'])==64
    assert broker.read('task','session','src/a.txt')==b'changed'


def test_precondition_conflict_precedes_intent(broker,log):
    with pytest.raises(PermissionError,match='precondition'):
        write(broker,log,expected=None)
    assert log.inspect()=={}
    assert broker.read('task','session','src/a.txt')==b'original'


@pytest.mark.parametrize('after_replace',[False,True])
def test_uncertain_write_reconciles_without_replay(broker,log,monkeypatch,after_replace):
    target=broker.grant.root/'src/a.txt'
    if after_replace:
        original=os.fsync
        def flush(fd):
            original(fd)
            if Path(os.readlink(f'/proc/self/fd/{fd}'))==target.parent:
                raise OSError('fixture after replacement')
        monkeypatch.setattr(os,'fsync',flush)
    else:
        monkeypatch.setattr(os,'replace',lambda *args,**kwargs: (_ for _ in ()).throw(OSError('fixture before replacement')))
    with pytest.raises(OSError):write(broker,log)
    operation,=log.inspect()
    assert log.inspect()[operation]['outcome']=='uncertain'
    content=target.read_bytes()
    recovered=Journal(log.root,task='task',session='session')
    result=reconcile(broker,recovered,operation,task='task',session='session')
    assert result==('applied' if after_replace else 'not_applied')
    assert target.read_bytes()==content
    assert recovered.inspect()[operation]['result']['reconciled']


def test_conflicting_recovery_preserves_file_and_unfinished_intent(broker,log,monkeypatch):
    monkeypatch.setattr(os,'replace',lambda *args,**kwargs: (_ for _ in ()).throw(OSError()))
    with pytest.raises(OSError):write(broker,log)
    operation,=log.inspect()
    target=broker.grant.root/'src/a.txt';target.write_bytes(b'custom change')
    with pytest.raises(PermissionError,match='conflicts'):
        reconcile(broker,log,operation,task='task',session='session')
    assert target.read_bytes()==b'custom change' and log.inspect()[operation]['outcome']=='uncertain'


def test_wrong_workspace_and_missing_read_authority_refused(broker,log,monkeypatch):
    monkeypatch.setattr(os,'replace',lambda *args,**kwargs: (_ for _ in ()).throw(OSError()))
    with pytest.raises(OSError):write(broker,log)
    operation,=log.inspect()
    other=broker.grant.root.parent/'other';other.mkdir();(other/'src').mkdir();(other/'src/a.txt').write_bytes(b'original')
    alternate=FileBroker(replace(broker.grant,root=other),broker.lease_root)
    with pytest.raises(PermissionError,match='identity'):
        reconcile(alternate,log,operation,task='task',session='session')
    denied=FileBroker(replace(broker.grant,read=()),broker.lease_root)
    with pytest.raises(PermissionError):reconcile(denied,log,operation,task='task',session='session')


def test_root_replacement_after_intent_stops_mutation(broker,log,monkeypatch):
    original=log.begin
    old=broker.grant.root.parent/'old'
    def begin(*args,**kwargs):
        operation=original(*args,**kwargs)
        broker.grant.root.rename(old)
        broker.grant.root.mkdir();(broker.grant.root/'src').mkdir()
        (broker.grant.root/'src/a.txt').write_bytes(b'original')
        return operation
    monkeypatch.setattr(log,'begin',begin)
    with pytest.raises(PermissionError,match='identity'):write(broker,log)
    assert (old/'src/a.txt').read_bytes()==b'original'
    assert (broker.grant.root/'src/a.txt').read_bytes()==b'original'


def test_absent_file_creation_and_legacy_unbound_reconciliation(broker,log):
    operation=broker.write_recorded('task','session','src/new.txt',b'new',expected_before=None,journal=log)
    assert log.inspect()[operation]['outcome']=='applied'
    old=log.begin('file_replace',{'path':'src/a.txt','before':digest(b'original'),'after':digest(b'changed')})
    with pytest.raises(PermissionError,match='identity'):
        reconcile(broker,log,old,task='task',session='session')


def test_recovery_rejects_property_conflict_even_with_expected_content(broker,log,monkeypatch):
    target=broker.grant.root/'src/a.txt'
    original=os.fsync
    def flush(fd):
        original(fd)
        if Path(os.readlink(f'/proc/self/fd/{fd}'))==target.parent:raise OSError('after replacement')
    monkeypatch.setattr(os,'fsync',flush)
    with pytest.raises(OSError):write(broker,log)
    operation,=log.inspect()
    target.chmod(0o700)
    with pytest.raises(PermissionError,match='conflicts'):
        reconcile(broker,log,operation,task='task',session='session')
    assert log.inspect()[operation]['outcome']=='uncertain'


@pytest.mark.parametrize('boundary', ['root', 'parent', 'leaf'])
def test_displaced_observation_stays_uncertain(broker, log, monkeypatch, boundary):
    from ls.core.agent import file_recovery
    with monkeypatch.context() as patch:
        patch.setattr(os, 'replace', lambda *args, **kwargs: (_ for _ in ()).throw(OSError()))
        with pytest.raises(OSError):
            write(broker, log)
    operation, = log.inspect()
    target = broker.grant.root / 'src/a.txt'
    displaced = {'root': broker.grant.root, 'parent': target.parent, 'leaf': target}[boundary]
    old = displaced.with_name(displaced.name + '-old')
    original = file_recovery.digest_descriptor
    def observe(fd, info):
        result = original(fd, info)
        displaced.rename(old)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'original')
        return result
    monkeypatch.setattr(file_recovery, 'digest_descriptor', observe)
    with pytest.raises(PermissionError, match='identity|properties'):
        reconcile(broker, log, operation, task='task', session='session')
    assert log.inspect()[operation]['outcome'] == 'uncertain'
    assert target.read_bytes() == b'original'
    old_target = old / 'src/a.txt' if boundary == 'root' else old / 'a.txt' if boundary == 'parent' else old
    assert old_target.read_bytes() == b'original'
