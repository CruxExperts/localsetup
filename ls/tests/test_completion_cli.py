import json,os,subprocess,sys,threading,time
from pathlib import Path
import pytest
from ls.core.agent.completion_cli import read_request


def test_completion_help_and_invalid_arguments_provider_free():
    root=Path(__file__).resolve().parents[2]
    base=[sys.executable,str(root/'ls/tools/localsetup.py'),'llm']
    result=subprocess.run([*base,'complete','--help'],capture_output=True,text=True)
    assert result.returncode==0 and '--request' in result.stdout and '--profile' in result.stdout
    result=subprocess.run([*base,'complete','--request','private-input'],capture_output=True,text=True)
    assert result.returncode==2 and json.loads(result.stdout)['status']=='invalid_request'
    assert not result.stderr and 'private-input' not in result.stdout


def test_completion_request_regular_file_bounds(tmp_path):
    path=tmp_path/'request';path.write_text('{"ok":true}')
    assert read_request(str(path),time.monotonic()+1,threading.Event())=='{"ok":true}'
    link=tmp_path/'link';link.symlink_to(path)
    with pytest.raises(OSError):read_request(str(link),time.monotonic()+1,threading.Event())
    path.write_bytes(b'x'*1048577)
    with pytest.raises(ValueError):read_request(str(path),time.monotonic()+1,threading.Event())
    with pytest.raises(TimeoutError):read_request(str(path),time.monotonic()-1,threading.Event())
