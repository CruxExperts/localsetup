import asyncio
import json

import httpx2 as httpx
import pytest

from ls.core.agent.profiles import parse, load
from ls.core.agent.provider_client import client
from ls.core.branding import user_agent


def config(**changes):
    return dict(base_url='https://fixture.invalid/v1', api='chat_completions', model='fixture', credential_env='TASK_KEY', timeout_seconds=5, capabilities=['streaming'], allow_loopback_http=False, **changes)


@pytest.mark.parametrize('field,value', [('base_url','http://remote.invalid/v1'), ('base_url','https://user:password@fixture.invalid'), ('base_url','https://fixture.invalid/v1?secret=yes'), ('base_url','https://fixture.invalid/a/../v1'), ('timeout_seconds',True), ('timeout_seconds',float('nan')), ('capabilities',['tools','tools']), ('credential_env',''), ('api','unknown')])
def test_invalid_profile(field,value):
    data=config();data[field]=value
    with pytest.raises(ValueError):parse(data)


def test_explicit_loopback_and_missing_credentials():
    data=config();data.update(base_url='http://127.0.0.1:1234/v1',allow_loopback_http=True)
    profile=parse(data)
    assert profile.endpoint=='http://127.0.0.1:1234/v1/chat/completions'
    with pytest.raises(ValueError,match='credential'):profile.credential({'OPENAI_API_KEY':'ambient'})


def test_profile_loading_rejects_duplicate_keys_and_creates_nothing(tmp_path):
    path=tmp_path/'profiles.json'
    with pytest.raises(ValueError):load(path,'test')
    assert not path.exists()
    path.write_text('{"schema_version":1,"schema_version":1,"profiles":{}}')
    path.chmod(0o644)
    with pytest.raises(ValueError,match='Duplicate'):load(path,'test')
    path.write_text(json.dumps({'schema_version':1,'profiles':{'test':config()}}))
    assert load(path,'test').model=='fixture'


@pytest.mark.parametrize('api', ['chat_completions','responses'])
def test_final_send_identity_credentials_and_no_retries(api,monkeypatch):
    captured=[]
    def receive(request):
        captured.append(request)
        return httpx.Response(429,json={'error':{'message':'fixture rate limit','type':'rate_limit'}})
    monkeypatch.setenv('OPENAI_API_KEY','ambient')
    monkeypatch.setenv('OPENAI_BASE_URL','https://wrong.invalid')
    monkeypatch.setenv('OPENAI_ORG_ID','ambient-org')
    monkeypatch.setenv('OPENAI_CUSTOM_HEADERS','X-Private-Context: must-not-disclose\nContent-Length: 1\nContent-Type: multipart/form-data')
    data=config();data['api']=api;profile=parse(data)
    async def run():
        from openai import RateLimitError
        async with client(profile,{'TASK_KEY':'explicit'},transport=httpx.MockTransport(receive)) as sdk:
            with pytest.raises(RateLimitError):
                if api=='responses':
                    await sdk.responses.create(model=profile.model,input='fixture',extra_headers={'User-Agent':'SDK override','Authorization':'Bearer override','Host':'wrong.invalid'})
                else:
                    await sdk.chat.completions.create(model=profile.model,messages=[{'role':'user','content':'fixture'}],extra_headers={'User-Agent':'SDK override','Authorization':'Bearer override','Host':'wrong.invalid'})
    asyncio.run(run())
    assert len(captured)==1
    request=captured[0]
    assert str(request.url)==profile.endpoint
    assert request.headers['user-agent']==user_agent()
    assert request.headers['authorization']=='Bearer explicit'
    assert request.headers['host']=='fixture.invalid'
    assert request.headers.get('openai-organization','')==''
    assert set(request.headers)=={'host','user-agent','authorization','content-type','accept','content-length'}
    assert int(request.headers['content-length'])==len(request.content)
    assert json.loads(request.content)['model']==profile.model


def test_redirect_never_discloses_to_second_endpoint():
    captured=[]
    def receive(request):
        captured.append(request)
        return httpx.Response(307,headers={'Location':'https://other.invalid/stolen'})
    async def run():
        from openai import APIStatusError
        async with client(parse(config()),{'TASK_KEY':'explicit'},transport=httpx.MockTransport(receive)) as sdk:
            with pytest.raises(APIStatusError):
                await sdk.chat.completions.create(model='fixture',messages=[])
    asyncio.run(run())
    assert len(captured)==1


@pytest.mark.parametrize('method,url', [('GET','https://fixture.invalid/v1/chat/completions'), ('POST','https://other.invalid/v1/chat/completions'), ('POST','https://fixture.invalid/v1/responses')])
def test_transport_rejects_unselected_destination(method,url):
    from ls.core.agent.provider_client import BoundTransport
    def unexpected(request):
        pytest.fail('out of profile transport dispatch')
    async def run():
        transport=BoundTransport(parse(config()),'explicit',httpx.MockTransport(unexpected))
        with pytest.raises(ValueError,match='outside'):
            await transport.handle_async_request(httpx.Request(method,url))
        await transport.aclose()
    asyncio.run(run())


def test_oversized_serialized_request_refused_before_send():
    from ls.core.agent.provider_client import BoundTransport
    def unexpected(request):
        pytest.fail('oversized request dispatched')
    async def run():
        profile=parse(config())
        transport=BoundTransport(profile,'explicit',httpx.MockTransport(unexpected))
        with pytest.raises(ValueError,match='16 MiB'):
            await transport.handle_async_request(httpx.Request('POST',profile.endpoint,content=b'x'*(16*1024*1024+1)))
        await transport.aclose()
    asyncio.run(run())
