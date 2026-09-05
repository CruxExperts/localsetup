import json
import os
from pathlib import Path
import threading
import time

import pytest

from ls.core.agent.run_cli import _grant, _state
from ls.core.agent.run_io import Streams, safe


def test_private_grant_and_workspace_boundary(tmp_path):
    tmp_path.chmod(0o700)
    workspace=tmp_path/'project';workspace.mkdir()
    path=tmp_path/'grant.json'
    path.write_text(json.dumps({'schema_version':1,'read':['src'],'write':['src'],'disclose':[], 'recipes':{}}));path.chmod(0o600)
    value, recipes=_grant(path,workspace)
    assert value['disclose']==[] and recipes=={}
    path.chmod(0o644)
    with pytest.raises(ValueError,match='private'):_grant(path,workspace)
    path.chmod(0o600)
    with pytest.raises(ValueError,match='separate'):_grant(path,tmp_path)
    link=tmp_path/'link';link.symlink_to(path)
    with pytest.raises(OSError):_grant(link,workspace)


def test_state_preserves_custom_content_and_refuses_shared_child(tmp_path):
    tmp_path.chmod(0o700)
    root=tmp_path/'state'
    _state(root)
    custom=root/'custom';custom.write_text('retain')
    _state(root);assert custom.read_text()=='retain'
    (root/'sessions').chmod(0o755)
    with pytest.raises(ValueError,match='private'):_state(root)


def test_prompt_eof_bounds_cancellation_and_safe_rendering():
    read,write=os.pipe()
    try:
        os.write(write,b'hello\n');os.close(write);write=None
        assert Streams(time.monotonic()+1,threading.Event(),input_fd=read).prompt()=='hello\n'
    finally:
        os.close(read)
        if write is not None:os.close(write)
    cancelled=threading.Event();cancelled.set()
    with pytest.raises(InterruptedError):Streams(time.monotonic()+1,cancelled).prompt()
    assert safe('\x1b[31m\u202eevil')=='\\u001b[31m\\u202eevil'


def test_blocked_output_deadline_restores_descriptor_mode():
    read,write=os.pipe()
    try:
        os.set_blocking(write,False)
        while True:
            try:os.write(write,b'x'*4096)
            except BlockingIOError:break
        os.set_blocking(write,True)
        start=time.monotonic()
        with pytest.raises(TimeoutError):Streams(start+0.05,threading.Event(),output_fd=write).write('blocked')
        assert time.monotonic()-start<1 and os.get_blocking(write)
    finally:os.close(read);os.close(write)


def test_loader_named_credential_never_becomes_exec_environment(monkeypatch,tmp_path):
    import argparse
    from contextlib import contextmanager
    from ls.core.agent import run_cli
    from ls.core.agent.profiles import Profile
    from ls.core.agent.run_options import arguments
    from ls.core.agent import runtime_install
    parser=argparse.ArgumentParser();arguments(parser)
    args=parser.parse_args(['--profile','coding','--grant',str(tmp_path/'grant'),'--resource-parent',str(tmp_path/'resource'),'--prompt-stdin'])
    profile=Profile('https://example.invalid/v1/','chat_completions','fixture','LD_PRELOAD',1,frozenset())
    monkeypatch.setattr(run_cli,'load',lambda *args:profile)
    monkeypatch.setenv('LD_PRELOAD','fixture-not-a-library')
    @contextmanager
    def selected(*args,**kwargs):yield tmp_path/'release'
    monkeypatch.setattr(runtime_install,'selected',selected)
    class Captured(Exception):pass
    def execute(path,argv,environment):
        assert set(environment)=={'PATH','LANG',run_cli._CREDENTIAL}
        assert environment[run_cli._CREDENTIAL]=='fixture-not-a-library'
        assert argv[1:4]==['-I','-B','-m']
        raise Captured
    monkeypatch.setattr(os,'execve',execute)
    with pytest.raises(Captured):run_cli.launch([],args)


def test_full_stderr_does_not_block_terminal_failure():
    from ls.core.agent.run_cli import failure
    read,write=os.pipe();out_read,out_write=os.pipe()
    try:
        os.set_blocking(write,False)
        while True:
            try:os.write(write,b'x'*4096)
            except BlockingIOError:break
        os.set_blocking(write,True)
        start=time.monotonic()
        assert failure('jsonl',0,'timed_out',124,'deadline expired',output_fd=out_write,diagnostic_fd=write)==124
        assert time.monotonic()-start<1 and os.get_blocking(write)
        assert json.loads(os.read(out_read,4096))['data']['status']=='timed_out'
    finally:
        for fd in (read,write,out_read,out_write):os.close(fd)
