import json
from pathlib import Path
import subprocess
import sys


def test_sdk_models_in_isolated_source_worker():
    root=Path(__file__).resolve().parents[2]
    result=subprocess.run([sys.executable,'-I','-B',str(root/'ls/tests/sdk_model_fixture.py'),str(root)],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    report=json.loads(result.stdout)
    assert [r['api'] for r in report['results']]==['chat_completions','responses']
    assert all(Path(p).is_relative_to(root/'vendor/lscli') for p in report['origins'].values())


def test_models_refuse_controller_process_before_sdk_import():
    import asyncio
    import pytest
    from ls.core.agent.sdk_models import model
    async def run():
        with pytest.raises(RuntimeError,match='isolated worker'):
            async with model(None,{},None):
                pytest.fail('controller model dispatch')
    asyncio.run(run())
    assert not any(name.startswith('pydantic_ai') for name in sys.modules)
