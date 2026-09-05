import asyncio
import json
from pathlib import Path
import socket
import subprocess
import sys
import time

import pytest

from ls.core.agent.broker_rpc import Channel
from ls.core.agent.checkpoint_rpc import CheckpointHandler
from ls.tests.test_session_owner import state, own, broker


def test_sdk_snapshot_crosses_rpc_and_survives_owner_restart(state,broker):
    root=Path(__file__).resolve().parents[2]
    left,right=socket.socketpair()
    channel=Channel(left,task='task',session='session',methods=frozenset({'checkpoint.save'}),expires=time.monotonic()+10)
    child=subprocess.Popen([sys.executable,'-I','-B',str(root/'ls/tests/sdk_persistence_fixture.py'),str(right.fileno()),str(root)],
                           pass_fds=(right.fileno(),),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    right.close()
    try:
        with own(state,broker,expires=time.monotonic()+10) as owner:
            handler=CheckpointHandler(owner,profile='a'*64,run_id='run')
            while True:
                try:channel.serve_once(handler,check=owner._check)
                except ConnectionError:break
            output,error=child.communicate(timeout=5)
            assert child.returncode==0,error
            report=json.loads(output)
        with own(state,broker) as resumed:
            assert resumed.resume_checkpoint(report['digest'],profile='a'*64)==report['messages'].encode()
            assert report['output']=='durable fixture' and report['lost_ack_not_promoted']
    finally:
        channel.close()
        if child.poll() is None:child.kill();child.wait()


def test_handler_rejects_payload_authority_fields(state,broker):
    with own(state,broker) as owner:
        handler=CheckpointHandler(owner,profile='a'*64,run_id='run')
        with pytest.raises(ValueError,match='schema'):
            handler('checkpoint.save',{'messages':'[]','step':0,'state':'complete','profile':'b'*64})
        with pytest.raises(ValueError,match='method'):
            handler('file.write',{})


def test_controller_cannot_import_sdk_store():
    from ls.core.agent.sdk_persistence import checkpoint_store
    with pytest.raises(RuntimeError,match='isolated worker'):
        checkpoint_store(None,None,run_id='run')
    assert not any(name.startswith('pydantic_ai') for name in sys.modules)
