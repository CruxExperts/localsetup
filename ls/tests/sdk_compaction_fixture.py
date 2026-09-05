"""Isolated compaction fixture with deterministic qualified provider transports."""
import asyncio,json,time
from pathlib import Path
import sys

api=sys.argv[2] if len(sys.argv)>2 else 'chat_completions'
if len(sys.argv)>=2:
    sys.path.insert(0,sys.argv[1]);payload=Path(sys.argv[1])/'./vendor/lscli'
else:
    import ls
    payload=Path(ls.__file__).parent/'_sdk_payload'
from ls.core.agent.sdk_imports import activate
finder=activate(payload)
from ls.core.agent.sdk_compaction import compact,SUMMARY_CONTEXT
from ls.core.agent.sdk_models import model
from ls.core.agent.profiles import parse
from ls.core.branding import user_agent
from pydantic_ai.messages import ModelMessagesTypeAdapter,ModelRequest,ModelResponse,UserPromptPart,TextPart,SystemPromptPart,ToolCallPart,ToolReturnPart
import httpx2 as httpx

async def main():
    calls=[];mode="success"
    def receive(request):
        calls.append(request)
        body=json.loads(request.content)
        assert body['stream'] and not body.get('tools') and 0<body['max_completion_tokens' if api=='chat_completions' else 'max_output_tokens']<=4096
        assert request.headers['user-agent']==user_agent()
        if mode=='error':return httpx.Response(500,json={'error':{'message':'fixture failure'}})
        summary='x'*65537 if mode=='oversize' else 'Retain the task and completed checks.'
        frames=[{'id':'fixture','object':'chat.completion.chunk','created':1,'model':'fixture',
          'choices':[{'index':0,'delta':{'role':'assistant','content':summary},'finish_reason':None}]},
          {'id':'fixture','object':'chat.completion.chunk','created':1,'model':'fixture',
          'choices':[{'index':0,'delta':{},'finish_reason':'stop'}],'usage':{'prompt_tokens':100,'completion_tokens':10,'total_tokens':110}}]
        content=''.join('data: '+json.dumps(frame)+'\n\n' for frame in frames)+'data: [DONE]\n\n'
        if api=='responses':
            from ls.tests.responses_stream_fixture import stream
            content=stream(1,text=summary,status=mode if mode in ('failed','incomplete','missing','conflicting') else 'completed')
        return httpx.Response(200,headers={'content-type':'text/event-stream'},content=content)
    profile=parse({'base_url':'https://fixture.invalid/v1/','api':api,'model':'fixture','credential_env':'KEY','timeout_seconds':5,'capabilities':['streaming'],'allow_loopback_http':False})
    history=ModelMessagesTypeAdapter.dump_json([ModelRequest(parts=[SystemPromptPart('Original system'),UserPromptPart('long original task '*1000)]),ModelResponse(parts=[TextPart('long work evidence '*1000)]),ModelRequest(parts=[UserPromptPart('Recent user task')]),ModelResponse(parts=[ToolCallPart('read_file',{'path':'a'},'call')]),ModelRequest(parts=[ToolReturnPart('read_file',{'content':'evidence'},'call')]),ModelResponse(parts=[TextPart('Recent answer')])])
    async with model(profile,{'KEY':'fixture'},finder,transport=httpx.MockTransport(receive)) as adapter:
        result=await compact(adapter,finder,history,keep_messages=2,token_limit=10000,expires=time.monotonic()+5,check=lambda:None)
        messages=ModelMessagesTypeAdapter.validate_json(result['messages'])
        assert len(messages)==4 and isinstance(messages[0].parts[-1],UserPromptPart)
        assert messages[0].parts[-1].content.startswith(SUMMARY_CONTEXT)
        assert messages[0].parts[0].content=='Original system'
        assert ModelMessagesTypeAdapter.dump_json(messages[1:])==ModelMessagesTypeAdapter.dump_json(ModelMessagesTypeAdapter.validate_json(history)[-3:])
        assert result['usage']['requests']==1 and len(result['messages'])<len(history)
        for kwargs in [{'keep_messages':256},{'expires':time.monotonic()-1}]:
            values=dict(keep_messages=2,token_limit=10000,expires=time.monotonic()+5,check=lambda:None);values.update(kwargs)
            try:await compact(adapter,finder,history,**values)
            except (ValueError,TimeoutError):pass
            else:raise AssertionError('Invalid compaction accepted')
        for failure_mode,limit in [('oversize',10000),('tokens',5),('error',10000)]+([(x,10000) for x in ('failed','incomplete','missing','conflicting')] if api=='responses' else []):
            mode=failure_mode
            before=len(calls)
            try:await compact(adapter,finder,history,keep_messages=2,token_limit=limit,expires=time.monotonic()+5,check=lambda:None)
            except Exception:pass
            else:raise AssertionError('Compaction failure accepted')
            assert len(calls)==before+1
    assert len(calls)==(8 if api=='responses' else 4)
    finder.verify_origins()
    print(json.dumps({'requests':1,'failure_requests':len(calls)-1,'user_agent':calls[0].headers['user-agent'],'native_tail_preserved':True,'summary_is_user_context':True}))
asyncio.run(main())
