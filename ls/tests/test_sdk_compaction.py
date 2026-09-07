import asyncio,json,subprocess,sys
from pathlib import Path

import pytest
from ls.core.agent.sdk_compaction import compact


@pytest.mark.parametrize('api',['chat_completions','responses'])
def test_compaction_native_primitive_and_actual_transport_identity(api):
    root=Path(__file__).resolve().parents[2]
    result=subprocess.run([sys.executable,'-I','-B',str(root/'ls/tests/sdk_compaction_fixture.py'),str(root),api],capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
    report=json.loads(result.stdout)
    assert report['requests']==1 and report['user_agent'].startswith('LocalSetup/')
    assert report['native_tail_preserved'] and report['summary_is_user_context']


def test_compaction_import_boundary():
    with pytest.raises(RuntimeError,match='isolated worker'):
        asyncio.run(compact(None,None,b'[]',keep_messages=0,token_limit=1,expires=1,check=lambda:None))
    assert not any(k.startswith('pydantic_ai') for k in sys.modules)
