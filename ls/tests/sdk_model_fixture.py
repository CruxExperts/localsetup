"""Isolated test-worker fixture; never contacts a provider."""
import asyncio
import json
from pathlib import Path
import sys

# Explicit source paths are used only by source tests. Installed proof omits them.
if len(sys.argv) == 2:
    sys.path.insert(0, sys.argv[1])
    payload = Path(sys.argv[1]) / 'vendor/lscli'
else:
    import ls
    payload = Path(ls.__file__).parent / '_sdk_payload'

from ls.core.agent.sdk_imports import activate
finder = activate(payload)
from ls.core.agent.sdk_models import model
from ls.core.agent.profiles import parse
from ls.core.branding import user_agent
import httpx2 as httpx
from pydantic_ai.messages import ModelRequest, UserPromptPart, SystemPromptPart, TextPart
from pydantic_ai.models import ModelRequestParameters


async def run():
    results = []
    for api in ('chat_completions', 'responses'):
        calls = []
        def receive(request):
            calls.append(request)
            body = json.loads(request.content)
            assert body['model'] == 'o1-mini'
            if api == 'chat_completions':
                assert body['messages'][0]['role'] == 'system'
            assert not body.get('tools')
            assert request.headers['user-agent'] == user_agent()
            assert request.headers['authorization'] == 'Bearer fixture-key'
            if api == 'chat_completions':
                response = {'id':'fixture','object':'chat.completion','created':1,'model':'fixture','choices':[{'index':0,'message':{'role':'assistant','content':'fixture answer'},'finish_reason':'stop'}],'usage':{'prompt_tokens':2,'completion_tokens':2,'total_tokens':4}}
            else:
                response = {'id':'fixture','object':'response','created_at':1,'model':'fixture','status':'completed','output':[{'type':'message','id':'message','status':'completed','role':'assistant','content':[{'type':'output_text','text':'fixture answer','annotations':[]}]}],'usage':{'input_tokens':2,'output_tokens':2,'total_tokens':4}}
            return httpx.Response(200,json=response)
        profile = parse(dict(base_url='https://fixture.invalid/v1/',api=api,model='o1-mini',credential_env='TASK_KEY',timeout_seconds=5,capabilities=[],allow_loopback_http=False))
        async with model(profile, {'TASK_KEY':'fixture-key'}, finder, transport=httpx.MockTransport(receive)) as adapter:
            assert adapter.profile['supports_tools'] is False
            assert adapter.profile['context_window'] is None
            assert 'openai_system_prompt_role' not in adapter.profile
            answer = await adapter.request([ModelRequest(parts=[SystemPromptPart('fixture instruction'), UserPromptPart('fixture prompt')])], None, ModelRequestParameters())
            assert ''.join(part.content for part in answer.parts if isinstance(part,TextPart)) == 'fixture answer'
        assert len(calls) == 1
        results.append({'api':api,'user_agent':calls[0].headers['user-agent'],'requests':1})
    print(json.dumps({'results':results,'origins':finder.verify_origins()},sort_keys=True))

asyncio.run(run())
