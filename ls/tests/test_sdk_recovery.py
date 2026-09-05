from pathlib import Path
import json
import subprocess
import sys

import pytest


def test_native_recovery_and_continuation_without_tools():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable,'-I','-B',str(root/'ls/tests/sdk_recovery_fixture.py'),str(root)],
                            capture_output=True,text=True,timeout=15)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['recovered_calls'] == 2 and report['refusals'] == 6 and report['continuation_calls'] == 1


def test_recovery_sdk_imports_stay_in_worker():
    from ls.core.agent.sdk_recovery import reconstruct
    with pytest.raises(RuntimeError,match='isolated worker'):
        reconstruct(None,b'[]',[],recipes={})
    assert not any(name.startswith('pydantic_ai') for name in sys.modules)
