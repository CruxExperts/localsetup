import hashlib
from pathlib import Path

import pytest
from dataclasses import replace
from ls.core.agent import process_rpc
from ls.core.agent.file_broker import FileBroker
from ls.core.agent.process_rpc import ProcessHandler,Recipe
from ls.core.agent.resource_group import Limits
from ls.core.agent.supervisor import Outcome
from ls.tests.test_session_owner import state,own,broker


def handler(owner,broker):
    storage=broker.grant.root.parent/'snapshots';storage.mkdir(mode=0o700)
    return ProcessHandler(owner,broker,profile='a'*64,run_id='run',runtimes=storage.parent/'runtime',snapshots=storage,
                          recipes={'test':Recipe(('/usr/bin/true',),('src/a.txt',),2)})


def request(owner):
    checkpoint=owner.save_checkpoint(b'[]',profile='a'*64,run_id='run',step=0,state='interrupted')
    return {'name':'test','checkpoint':checkpoint,'call_id':'call'}


def test_recipe_projection_identity_and_replay_gate(state,broker,monkeypatch):
    allowed=FileBroker(replace(broker.grant,disclose=('src',)),broker.lease_root)
    with own(state,broker) as owner:
        dispatch=handler(owner,allowed)
        dispatch.resource_parent=Path('/sys/fs/cgroup/explicit')
        dispatch.limits=Limits(tasks=8)
        seen=[]
        def run(runtimes,grant,journal,**kwargs):
            assert grant.command==('/usr/bin/true',) and grant.disclose_output
            assert grant.resource_parent==dispatch.resource_parent and grant.limits==dispatch.limits
            assert (grant.staging/'src/a.txt').read_bytes()==b'original'
            assert grant.expires<=owner.expires
            operation=journal.begin('process',{'argv_sha256':'b'*64,'snapshot_sha256':kwargs['snapshot_sha256']},
                                    checkpoint=kwargs['checkpoint'],tool_call=kwargs['tool_call'])
            from ls.core.agent.tool_results import _digest
            journal.finish(operation,'completed',evidence_sha256=_digest({'status':'completed','returncode':0,'data':{'stdout':'passed','stderr':''}}))
            seen.append(operation)
            return Outcome('completed',0,{'stdout':'passed','stderr':''})
        monkeypatch.setattr(process_rpc,'run_recorded',run)
        result=dispatch('process.run',request(owner))
        assert result['operation']==seen[0] and result['output']['stdout']=='passed'
        with pytest.raises(ValueError,match='already has'):
            dispatch('process.run',request(owner))
        assert len(list(dispatch.snapshots.iterdir()))==1 and len(seen)==1
    assert (broker.grant.root/'src/a.txt').read_bytes()==b'original'


def test_recipe_payload_and_disclosure_refused_before_projection(state,broker):
    with own(state,broker) as owner:
        dispatch=handler(owner,broker);data=request(owner)
        with pytest.raises(PermissionError,match='granted'):
            dispatch('process.run',data|{'name':'other'})
        with pytest.raises(ValueError,match='schema'):
            dispatch('process.run',data|{'command':['/usr/bin/true']})
        with pytest.raises(PermissionError,match='disclosure'):
            dispatch('process.run',data)
        assert not list(dispatch.snapshots.iterdir()) and owner.inspect()=={}


def test_invalid_recipe_and_controller_import_refused():
    with pytest.raises(ValueError):Recipe(('/bin/sh',),('file',),1)
    with pytest.raises(ValueError):Recipe(('/usr/bin/true',),('file',),True)
    from ls.core.agent.sdk_process_tool import process_tool
    with pytest.raises(RuntimeError,match='isolated worker'):process_tool(None,None)


def test_exposed_system_runtime_refused_before_projection(state,broker):
    allowed=FileBroker(replace(broker.grant,disclose=('src',)),broker.lease_root)
    with own(state,broker) as owner:
        dispatch=handler(owner,allowed)
        dispatch.runtimes=Path('/usr/runtime')
        with pytest.raises(ValueError,match='separate'):
            dispatch('process.run',request(owner))
        assert not list(dispatch.snapshots.iterdir()) and owner.inspect()=={}


def test_process_grant_expiring_during_receipt_flush_refuses_delivery(state,broker,monkeypatch):
    import time
    from ls.core.agent import tool_results
    allowed=FileBroker(replace(broker.grant,disclose=('src',)),broker.lease_root)
    captured=[]
    with own(state,broker) as owner:
        dispatch=handler(owner,allowed)
        def run(runtimes,grant,journal,**kwargs):
            operation=journal.begin('process',{'argv_sha256':'b'*64,'snapshot_sha256':kwargs['snapshot_sha256']},
                checkpoint=kwargs['checkpoint'],tool_call=kwargs['tool_call'])
            output={'stdout':'passed','stderr':''}
            journal.finish(operation,'completed',evidence_sha256=tool_results._digest({'status':'completed','returncode':0,'data':output}))
            captured.append(grant)
            return Outcome('completed',0,output)
        original=tool_results.save
        def flush(*args,**kwargs):
            result=original(*args,**kwargs)
            # Only the narrower recipe grant expires; session authority remains live.
            monkeypatch.setattr(time,'monotonic',lambda:captured[0].expires+0.01)
            return result
        monkeypatch.setattr(process_rpc,'run_recorded',run)
        monkeypatch.setattr(tool_results,'save',flush)
        with pytest.raises(PermissionError,match='expired'):
            dispatch('process.run',request(owner))
        owner._check()
        operation,=owner.inspect()
        assert tool_results.recover(owner,operation,profile='a'*64)['result']['output']['stdout']=='passed'
