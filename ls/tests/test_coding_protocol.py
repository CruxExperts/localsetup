import json
from types import SimpleNamespace

import pytest
from ls.core.agent.coding_protocol import CodingHandler,request,profile_digest,terminal


def payload():
    return {'schema_version':1,'run_id':'run','profile':{'base_url':'https://example.com/v1/','api':'chat_completions','model':'model',
        'credential_env':'KEY','timeout_seconds':2,'capabilities':['tools','streaming'],'allow_loopback_http':False},
        'credential':'fixture','prompt':'Edit fixture','instructions':'Use granted tools','history':None,'request_limit':8,'tool_limit':16,'token_limit':32768}


def handler():
    p=payload();checks=[];events=[]
    owner=SimpleNamespace(_checkpoint=lambda x:{'run_id':'run'},resume_checkpoint=lambda *a,**k:checks.append('checkpoint'))
    tools=SimpleNamespace(profile=profile_digest(p['profile']),run_id='run',owner=owner)
    return CodingHandler(tools,p,events.append,lambda:checks.append('authority')),events,checks


def test_start_stream_checkpoint_and_process_receipt():
    h,events,checks=handler()
    with pytest.raises(ValueError,match='start'):h('stream.event',{'event':{}})
    assert h('run.start',{})['credential']=='fixture'
    with pytest.raises(ValueError,match='once'):h('run.start',{})
    assert h('stream.event',{'event':{'text':'hello'}})=={'accepted':1}
    result={'checkpoint':'a'*64,'output':'done','usage':{'requests':1}}
    assert h('run.finish',result)=={'checkpoint':'a'*64} and 'checkpoint' in checks
    assert terminal(json.dumps({'schema_version':1,'status':'completed','checkpoint':'a'*64}).encode(),h.finished)==result
    with pytest.raises(ValueError,match='already'):h('stream.event',{'event':{}})
    with pytest.raises(ValueError):terminal(b'{}',h.finished)


@pytest.mark.parametrize('field,value',[('credential','bad token'),('request_limit',True),('tool_limit',257),('history',4),('instructions','')])
def test_request_refuses_invalid_authority_inputs(field,value):
    with pytest.raises(ValueError):request(payload()|{field:value})


def test_profile_and_foreign_result_checkpoint_refused():
    h,_,_=handler();p=payload();p['profile']['model']='other'
    with pytest.raises(PermissionError):CodingHandler(h.tools,p,lambda x:None,lambda:None)
    h('run.start',{});h.tools.owner._checkpoint=lambda x:{'run_id':'other'}
    with pytest.raises(PermissionError):h('run.finish',{'checkpoint':'a'*64,'output':'done','usage':{}})
    assert h.finished is None


def test_stream_overflow_does_not_reach_sink():
    h,events,_=handler();h('run.start',{})
    with pytest.raises(ValueError,match='budget'):h('stream.event',{'event':{'text':'x'*(1024*1024)}})
    assert not events
