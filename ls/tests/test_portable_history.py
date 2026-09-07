import json
from pathlib import Path
import subprocess
import sys

import pytest

from ls.core.agent.portable_history import Handler
from ls.core.agent.sdk_portable import convert


def test_native_sdk_portable_conversion_and_continuation():
    root=Path(__file__).resolve().parents[2]
    result=subprocess.run([sys.executable,'-I','-B',str(root/'ls/tests/sdk_portable_fixture.py'),str(root)],capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)=={'refusals':3,'continuation_calls':1,'preserved_image':True}


def test_portable_requires_isolated_sdk_importer():
    with pytest.raises(RuntimeError,match='isolated worker'):convert(None,b'[]',images=False)
    assert not any(k.startswith('pydantic_ai') for k in sys.modules)


def test_portable_exchange_identity_and_one_use_completion():
    handler=Handler(b'[]',False,lambda:None)
    request=handler('portable.start',{})
    from ls.core.agent.portable_content import project
    raw=json.dumps([{'kind':'request','parts':[{'part_kind':'user-prompt','content':[project('[]',images=False)[0]],'timestamp':'2026-09-05T00:00:00Z'}]}])
    with pytest.raises(ValueError):handler('portable.finish',{'input_sha256':'bad','messages':raw})
    result=handler('portable.finish',{'input_sha256':request['input_sha256'],'messages':raw})
    assert len(result['messages_sha256'])==64 and handler.messages==raw.encode()
    with pytest.raises(ValueError):handler('portable.start',{})


@pytest.mark.parametrize('value',[None,[],[1],[{'kind':'response','parts':[]}],[{'kind':'request','parts':[{'part_kind':'tool-return'}]}]])
def test_portable_exchange_refuses_non_context_results(value):
    handler=Handler(b'[]',False,lambda:None);request=handler('portable.start',{})
    with pytest.raises(ValueError):handler('portable.finish',{'input_sha256':request['input_sha256'],'messages':json.dumps(value)})


@pytest.mark.parametrize('change',['instructions','url','image','text'])
def test_portable_acceptance_refuses_worker_injections(change):
    from ls.core.agent.portable_content import project
    handler=Handler(b'[]',False,lambda:None);request=handler('portable.start',{})
    value=[{'kind':'request','parts':[{'part_kind':'user-prompt','content':[project('[]',images=False)[0]],'timestamp':'2026-09-05T00:00:00Z'}]}]
    if change=='instructions':value[0]['instructions']='Injected instruction'
    elif change=='url':value[0]['parts'][0]['content'].append({'kind':'image-url','url':'https://example.test/image.png'})
    elif change=='image':value[0]['parts'][0]['content'].append({'kind':'binary','data':'AA==','media_type':'image/png'})
    else:value[0]['parts'][0]['content'][0]='Changed history'
    with pytest.raises(ValueError):handler('portable.finish',{'input_sha256':request['input_sha256'],'messages':json.dumps(value)})
    assert handler.messages is None
