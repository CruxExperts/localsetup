import os
from pathlib import Path

import pytest
from ls.core.agent import resource_group as groups


@pytest.mark.parametrize('kwargs',[{'tasks':True},{'tasks':513},{'memory_bytes':1},{'cpu_percent':0}])
def test_limits_reject_unbounded_values(kwargs):
    with pytest.raises(ValueError):groups.Limits(**kwargs)


def test_parent_requires_explicit_delegation(tmp_path):
    with pytest.raises(ValueError):groups._parent(tmp_path)
    with pytest.raises(ValueError):groups._parent(Path('/sys/fs/cgroup'))


@pytest.fixture
def controls(tmp_path,monkeypatch):
    calls=[]
    monkeypatch.setattr(groups,'_parent',lambda p:os.open(tmp_path,os.O_RDONLY|os.O_DIRECTORY))
    mkdir=os.mkdir
    def create(name,*args,**kwargs):
        mkdir(name,*args,**kwargs)
        child=tmp_path/name
        for key in (*groups.Limits().settings(),'cgroup.procs'):(child/key).write_text('')
    monkeypatch.setattr(groups.os,'mkdir',create)
    def drain(fd):calls.append('drain')
    monkeypatch.setattr(groups,'_drain',drain)
    rmdir=os.rmdir
    def remove(name,**kwargs):
        calls.append('remove')
        for p in (tmp_path/name).iterdir():p.unlink()
        rmdir(name,**kwargs)
    monkeypatch.setattr(groups.os,'rmdir',remove)
    return tmp_path,calls


def test_limits_checked_before_membership_and_handle_expires(controls):
    root,calls=controls
    with groups.resource_group(root,groups.Limits()) as group:
        assert calls==['drain']
        with group.membership() as fd:assert os.fstat(fd)
        with pytest.raises(OSError):os.fstat(fd)
        child=next(root.iterdir());(child/'pids.max').write_text('65')
        with pytest.raises(RuntimeError,match='changed'):
            with group.membership():pytest.fail('altered group exposed')
    assert calls==['drain','drain','remove'] and not list(root.iterdir())
    with pytest.raises(RuntimeError,match='ended'):group.verify()


def test_body_failure_still_drains_and_removes(controls):
    root,calls=controls
    with pytest.raises(ValueError,match='payload'):
        with groups.resource_group(root,groups.Limits()):raise ValueError('payload')
    assert calls==['drain','drain','remove'] and not list(root.iterdir())


def test_failed_setting_never_yields_and_cleans(controls,monkeypatch):
    root,calls=controls
    def fail(*args):raise PermissionError('setting denied')
    monkeypatch.setattr(groups,'_write',fail)
    with pytest.raises(PermissionError,match='denied'):
        with groups.resource_group(root,groups.Limits()):pytest.fail('unbounded group yielded')
    assert calls==['drain','remove']


def test_drain_failure_retains_group_and_expires_handle(controls,monkeypatch):
    root,calls=controls
    def drain(fd):
        calls.append('drain')
        if len(calls)>1:raise RuntimeError('still populated')
    monkeypatch.setattr(groups,'_drain',drain)
    with pytest.raises(RuntimeError,match='populated'):
        with groups.resource_group(root,groups.Limits()) as group:pass
    assert len(list(root.iterdir()))==1 and 'remove' not in calls
    with pytest.raises(RuntimeError,match='ended'):group.verify()
