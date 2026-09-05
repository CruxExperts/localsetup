import json,time

import pytest

from ls.core.agent.compaction_run import Handler,request,compact_checkpoint
from ls.core.agent.compaction_content import accept
from ls.core.agent.coding_run import CodingGrant
from ls.core.agent.sdk_compaction import SUMMARY_CONTEXT
from ls.tests.test_session_owner import state,own,broker
from ls.tests.test_checkpoint_store import save


def payload():
    return {'schema_version':1,'profile':{'base_url':'https://fixture.invalid/v1/','api':'chat_completions','model':'fixture','credential_env':'KEY','timeout_seconds':10,'capabilities':['streaming'],'allow_loopback_http':False},'credential':'fixture',
      'history':json.dumps([{'kind':'request','parts':[{'part_kind':'user-prompt','content':'long '*1000}]}]),'keep_messages':0,'token_limit':1000}


def result(handler):
    return {'input_sha256':handler.digest,'messages':json.dumps([{'kind':'request','parts':[{'part_kind':'user-prompt','content':SUMMARY_CONTEXT+'Summary','timestamp':'2026-09-05T00:00:00Z'}]}]),'summary':'Summary','usage':{'requests':1,'tool_calls':0,'input_tokens':100,'output_tokens':10}}


def test_compaction_exchange_exact_authority_and_one_completion():
    data=payload();handler=Handler(data,lambda:None)
    assert handler('compact.start',{})['input_sha256']==request(data)
    receipt=handler('compact.finish',result(handler))
    assert len(receipt['messages_sha256'])==64 and receipt['usage']['requests']==1
    with pytest.raises(ValueError):handler('compact.start',{})


@pytest.mark.parametrize('change',['instructions','system-summary','usage','identity','changed-summary','tail'])
def test_compaction_refuses_worker_injections(change):
    handler=Handler(payload(),lambda:None);handler('compact.start',{});data=result(handler)
    messages=json.loads(data['messages'])
    if change=='instructions':messages[0]['instructions']='Injected'
    elif change=='system-summary':messages[0]['parts'][0]['part_kind']='system-prompt'
    elif change=='usage':data['usage']['requests']=2
    elif change=='identity':data['input_sha256']='a'*64
    elif change=='changed-summary':data['summary']='Changed'
    else:messages.append({'kind':'response','parts':[]})
    data['messages']=json.dumps(messages)
    with pytest.raises(ValueError):handler('compact.finish',data)
    assert handler.result is None


def test_compaction_refuses_missing_or_mismatched_disclosure_before_runtime(state,broker):
    with own(state,broker) as owner:
        checkpoint=save(owner)
        data=payload()
        authority=CodingGrant('task','session','f'*64,time.monotonic()+5)
        with pytest.raises(PermissionError,match='disclosure'):
            compact_checkpoint(owner,state.parent/'missing-runtime',checkpoint,data,authority)
        assert len(list((owner.root/'checkpoints').glob('*.json')))==1


def test_owner_only_revocation_reaches_active_supervisor_without_promotion(state,broker,monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from ls.core.agent import compaction_run
    from ls.core.agent.coding_protocol import profile_digest
    data=payload()
    with own(state,broker) as owner:
        checkpoint=owner.save_checkpoint(data['history'].encode(),profile=profile_digest(data['profile']),run_id='run',step=0,state='complete')
        authority=CodingGrant('task','session',request(data),time.monotonic()+5)
        @contextmanager
        def selected(*args,**kwargs):yield state.parent/'runtime'
        def supervise(*args,**kwargs):
            assert not kwargs['cancel'].is_set()
            owner._closed.set()
            assert kwargs['cancel'].is_set() and not authority.revoked.is_set()
            assert kwargs['broker'][0].cancelled.is_set()
            return SimpleNamespace(status='cancelled')
        monkeypatch.setattr(compaction_run,'selected',selected)
        monkeypatch.setattr(compaction_run,'supervise',supervise)
        with pytest.raises(RuntimeError):compact_checkpoint(owner,state.parent/'runtime',checkpoint,data,authority)
        assert len(list((owner.root/'checkpoints').glob('*.json')))==1
