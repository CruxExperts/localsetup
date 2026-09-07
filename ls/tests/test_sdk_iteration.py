import asyncio
import json
from pathlib import Path
import subprocess
import sys

import pytest


def test_isolated_sdk_iteration_streaming_snapshots_and_bounds():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, '-I', '-B', str(root/'ls/tests/sdk_iteration_fixture.py'), str(root)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['tool_calls'] == 1 and report['stream_events'] > 0 and report['snapshot_state'] == 'complete'
    assert all(Path(origin).is_relative_to(root/'vendor/lscli') for origin in report['origins'].values())


def test_iteration_refuses_controller_before_import():
    from ls.core.agent.sdk_iteration import iterate
    with pytest.raises(RuntimeError, match='isolated worker'):
        asyncio.run(iterate(None,None,prompt='',instructions='',tools=(),store=None,on_event=None,
                            check=None,expires=0,run_id='',conversation_id=''))
    assert not any(name.startswith('pydantic_ai') for name in sys.modules)
