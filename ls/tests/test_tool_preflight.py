from contextlib import contextmanager
import json
from pathlib import Path
import threading
import time

import pytest
from ls.core.agent import tool_preflight as preflight
from ls.core.agent.resource_group import Limits
from ls.core.agent.sandbox import ProcessGrant
from ls.core.agent.supervisor import Outcome


@pytest.fixture
def probe(tmp_path,monkeypatch):
    scratch=tmp_path/'scratch';scratch.mkdir(mode=0o700)
    root=tmp_path/'runtime';root.mkdir()
    held=[]
    @contextmanager
    def selected(*args,**kwargs):
        held.append(True)
        try:yield root/'release'
        finally:held.pop()
    monkeypatch.setattr(preflight,'selected',selected)
    def run(runtimes,grant,**kwargs):
        assert held and grant.resource_parent==Path('/sys/fs/cgroup/explicit')
        assert (grant.staging/'input').read_bytes()==b'preflight'
        data={'schema':1,'namespaces':{n:preflight.os.stat('/proc/self/ns/'+n).st_ino+1 for n in preflight.NAMESPACES},
              'network':['lo'],'capacity':{'/work':512*1024*1024,'/tmp':64*1024*1024}}
        return Outcome('completed',0,{'stdout':json.dumps(data),'stderr':''})
    monkeypatch.setattr(preflight,'run',run)
    return root,scratch,held


def qualify(probe,**kwargs):
    root,scratch,held=probe
    return preflight.qualified_tools(root,scratch,Path('/sys/fs/cgroup/explicit'),task='task',session='session',
                                     expires=time.monotonic()+3,limits=Limits(),**kwargs)


def test_preflight_holds_runtime_and_expires_bound_grants(probe):
    with qualify(probe) as result:
        assert probe[2] and not list(probe[1].iterdir())
        grant=result.bind(ProcessGrant('task','session',probe[1],('/usr/bin/true',),time.monotonic()+5))
        assert grant.expires==result.expires and grant.resource_parent==result.resource_parent
        result.check('task','session')
        with pytest.raises(PermissionError):result.check('foreign','session')
    assert not probe[2] and not list(probe[1].iterdir())
    with pytest.raises(PermissionError):result.check('task','session')
    with pytest.raises(PermissionError):grant.check('task','session')


@pytest.mark.parametrize('outcome',[Outcome('failed',1),Outcome('cancelled',None),Outcome('completed',0,{'stdout':'{}','stderr':''}),Outcome('completed',0,{'stdout':'{}','stderr':'warning'})])
def test_failed_probe_never_dispatches_caller(probe,monkeypatch,outcome):
    monkeypatch.setattr(preflight,'run',lambda *a,**k:outcome)
    with pytest.raises((ValueError,RuntimeError)):
        with qualify(probe):pytest.fail('provider could dispatch')
    assert not probe[2] and not list(probe[1].iterdir())


def test_revoked_preflight_does_not_launch(probe,monkeypatch):
    revoked=threading.Event();revoked.set()
    monkeypatch.setattr(preflight,'run',lambda *a,**k:pytest.fail('must not launch'))
    with pytest.raises(PermissionError):
        with qualify(probe,revoked=revoked):pass


def test_namespace_and_capacity_claims_require_evidence():
    host={n:1 for n in preflight.NAMESPACES}
    data={'schema':1,'namespaces':{n:2 for n in host},'capacity':{'/work':1,'/tmp':1},'network':['lo']}
    preflight._validate(data,host)
    for changes in ({'namespaces':host},{'network':['eth0']},{'capacity':{'/work':2**40,'/tmp':1}},{'schema':True}):
        with pytest.raises(ValueError):preflight._validate(data|changes,host)
