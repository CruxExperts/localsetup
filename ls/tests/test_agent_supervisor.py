import sys
import threading
import json

import pytest

from ls.core.agent.supervisor import supervise
from ls.core.agent.worker_protocol import event, probe_request


def run(tmp_path, code, *, timeout=2, cancel=None):
    return supervise([sys.executable,'-I','-B','-c',code], b'{}',cwd=tmp_path,environment={},timeout=timeout,cancel=cancel)


def valid():
    return event(0,'ready',{}) + event(1,'result',{'schema_version':1,'status':'qualified','origins':{'pydantic_ai':'/fixture/__init__.py'}})


def test_success_requires_protocol_and_process(tmp_path):
    data=valid()
    outcome=run(tmp_path,f'import sys;sys.stdin.read();sys.stdout.buffer.write({data!r})')
    assert outcome.status=='completed' and outcome.returncode==0
    outcome=run(tmp_path,f'import sys;sys.stdout.buffer.write({data!r});sys.exit(4)')
    assert outcome.status=='failed' and outcome.data is None


@pytest.mark.parametrize('data',[b'',b'not json\n',event(0,'result',{}),valid()+event(2,'result',{}),valid().replace(b'"sequence": 1',b'"sequence": true'),valid().replace(b'"sequence": 1',b'"sequence": 9, "sequence": 1')])
def test_invalid_protocol(tmp_path,data):
    outcome=run(tmp_path,f'import sys;sys.stdout.buffer.write({data!r})')
    assert outcome.status=='protocol_error'


@pytest.mark.parametrize('stream,amount',[('stdout',1024*1024+1),('stderr',64*1024+1)])
def test_output_limits(tmp_path,stream,amount):
    outcome=run(tmp_path,f'import sys;sys.{stream}.buffer.write(b"x"*{amount});sys.{stream}.flush();import time;time.sleep(30)')
    assert outcome.status=='output_limit' and outcome.returncode is not None


def test_timeout_and_active_cancellation(tmp_path):
    assert run(tmp_path,'import time;time.sleep(30)',timeout=.05).status=='timed_out'
    cancel=threading.Event()
    timer=threading.Timer(.05,cancel.set);timer.start()
    try:
        outcome=run(tmp_path,'import time;time.sleep(30)',cancel=cancel)
    finally:
        timer.cancel();timer.join()
    assert outcome.status=='cancelled' and outcome.returncode is not None


def test_precancel_never_spawns(tmp_path):
    cancel=threading.Event();cancel.set()
    assert run(tmp_path,'raise AssertionError()',cancel=cancel).returncode is None


def test_parent_exit_tears_down_pipe_holding_descendant(tmp_path):
    code="import os,time,sys;pid=os.fork();time.sleep(30) if pid==0 else sys.exit(2)"
    outcome=run(tmp_path,code,timeout=1)
    assert outcome.status=='failed' and outcome.returncode==2


def test_probe_request_strict_version():
    probe_request(b'{"schema_version":1,"operation":"probe"}')
    for raw in [b'',b'{"schema_version":true,"operation":"probe"}',b'{"schema_version":1,"operation":"run"}',b'{"schema_version":2,"schema_version":1,"operation":"probe"}']:
        with pytest.raises(ValueError):probe_request(raw)
