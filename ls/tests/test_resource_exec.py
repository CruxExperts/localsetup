import os
from pathlib import Path
import subprocess
import time
from contextlib import contextmanager

import pytest
from ls.core.agent import sandbox, process_broker
from ls.core.agent.supervisor import supervise
from ls.tests.test_agent_sandbox import invocation


def test_membership_precedes_exec_and_failed_join_prevents_payload(tmp_path):
    script=Path('ls/core/agent/resource_exec.py').resolve()
    marker=tmp_path/'ran'
    code=f"from pathlib import Path;Path({str(marker)!r}).write_text('yes')"
    fd=os.open(tmp_path/'membership',os.O_RDWR|os.O_CREAT,0o600)
    try:
        command=['/usr/bin/python3','-I','-B',str(script),str(fd),'--','/usr/bin/python3','-I','-B','-c',code]
        process=subprocess.Popen(command,pass_fds=(fd,));assert process.wait(timeout=3)==0
        os.lseek(fd,0,0);assert os.read(fd,100)==str(process.pid).encode()
        assert marker.read_text()=='yes';marker.unlink()
    finally:os.close(fd)
    command[4]='99999'
    result=subprocess.run(command,capture_output=True,timeout=3)
    assert result.returncode!=0 and not marker.exists()


def test_resource_scope_wraps_sealed_launcher(invocation,monkeypatch):
    from dataclasses import replace
    root,grant,held,binary=invocation
    live=[]
    class Group:
        @contextmanager
        def membership(self):
            live.append('member')
            try:yield 42
            finally:live.pop()
    @contextmanager
    def scope(parent,limits):
        assert parent==Path('/sys/fs/cgroup/delegation')
        live.append('group')
        try:yield Group()
        finally:live.pop()
    monkeypatch.setattr(sandbox,'resource_group',scope)
    grant=replace(grant,resource_parent=Path('/sys/fs/cgroup/delegation'))
    with sandbox.invocation(root,grant,task='task',session='session') as launch:
        assert live==['group','member'] and held
        assert launch.pass_fds==(42,)
        assert launch.command[:7]==(str(binary.parents[2]/'venv/bin/python'),'-I','-B','-m','ls.core.agent.resource_exec','42','--')
        assert launch.command[7]==str(binary)
    assert not held and not live


def test_authority_rechecked_after_resource_cleanup(tmp_path,monkeypatch):
    grant=sandbox.ProcessGrant('task','session',tmp_path,('/usr/bin/true',),time.monotonic()+5,True)
    @contextmanager
    def launch(*args,**kwargs):
        try:yield sandbox.Invocation(grant.command,tmp_path,{})
        finally:grant.revoked.set()
    monkeypatch.setattr(process_broker,'invocation',launch)
    monkeypatch.setattr(process_broker,'supervise',lambda *a,**k:process_broker.Outcome('completed',0,{'stdout':'secret'}))
    result=process_broker.run(tmp_path,grant,task='task',session='session',provider=True)
    assert result.status=='cancelled' and result.data is None


@pytest.mark.parametrize('fds',[(True,),(-1,),(3,3),[3]])
def test_supervisor_refuses_invalid_inherited_descriptors(tmp_path,fds):
    with pytest.raises(ValueError,match='descriptors'):
        supervise(['/usr/bin/true'],b'',cwd=tmp_path,environment={},timeout=1,pass_fds=fds)
