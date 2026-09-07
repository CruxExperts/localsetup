"""Isolated Responses coding stream and native-history qualification."""
import asyncio,json,time
from pathlib import Path
import sys

if len(sys.argv)==2:
    sys.path.insert(0,sys.argv[1]);payload=Path(sys.argv[1])/'./vendor/lscli'
else:
    import ls
    payload=Path(ls.__file__).parent/'_sdk_payload'
from ls.core.agent.sdk_imports import activate
finder=activate(payload)
from ls.core.agent.sdk_models import model
from ls.core.agent.sdk_iteration import iterate
from ls.core.agent.profiles import parse
from ls.core.branding import user_agent
from ls.tests.responses_stream_fixture import stream
from pydantic_ai.tools import Tool
from pydantic_ai_harness.step_persistence import InMemoryStepStore
import httpx2 as httpx

async def main():
    requests=[];effects=[];events=[]
    def receive(request):
        body=json.loads(request.content);requests.append(body)
        assert request.url.path=='/v1/responses' and request.headers['user-agent']==user_agent()
        assert body['stream'] and not body.get('previous_response_id')
        turn=len(requests)
        if turn==1:return httpx.Response(200,headers={'content-type':'text/event-stream'},content=stream(turn,name='fixture',arguments={'value':'original'}))
        returned=[item for item in body['input'] if item.get('type')=='function_call_output']
        assert len(returned)==1 and 'original' in returned[0]['output']
        return httpx.Response(200,headers={'content-type':'text/event-stream'},content=stream(turn,text='done' if turn==2 else 'resumed'))
    profile=parse({'base_url':'https://fixture.invalid/v1/','api':'responses','model':'fixture','credential_env':'KEY','timeout_seconds':5,'capabilities':['tools','streaming'],'allow_loopback_http':False})
    async def fixture(value:str)->str:effects.append(value);return value
    async def emit(raw):events.append(raw)
    common=dict(finder=finder,prompt='Use fixture then answer',instructions='Use granted tools',tools=(Tool(fixture,sequential=True,max_retries=0),),store=InMemoryStepStore(),on_event=emit,check=lambda:None,expires=time.monotonic()+10,run_id='run',conversation_id='session')
    async with model(profile,{'KEY':'fixture'},finder,transport=httpx.MockTransport(receive)) as adapter:
        result=await iterate(adapter,**common)
        assert result['output']=='done' and effects==['original'] and b'resp_2' in result['messages']
        resumed=await iterate(adapter,**(common|{'history':result['messages'],'run_id':'resume'}))
        assert resumed['output']=='resumed' and effects==['original']
    refused=[]
    for status in ('failed','incomplete','missing','conflicting'):
        bad_calls=[]
        def rejected(request):
            bad_calls.append(request)
            if len(bad_calls)>1:raise ValueError('Unexpected repeat request')
            return httpx.Response(200,headers={'content-type':'text/event-stream'},content=stream(1,name='fixture',arguments={'value':'must-not-execute'},status=status))
        async with model(profile,{'KEY':'fixture'},finder,transport=httpx.MockTransport(rejected)) as adapter:
            try:await iterate(adapter,**(common|{'run_id':'bad-'+status}))
            except Exception:pass
            else:raise AssertionError('Unfinished provider output accepted')
        assert effects==['original'], (status,effects)
        assert len(bad_calls)==1,(status,len(bad_calls))
        refused.append(status)
    assert len(requests)==3 and events
    finder.verify_origins()
    print(json.dumps({'requests':3,'tool_calls':len(effects),'native_resume':True,'stream_events':len(events),'refused':refused}))
asyncio.run(main())
