"""Isolated deterministic SDK snapshot RPC fixture."""
import asyncio
import json
from pathlib import Path
import socket
import sys
import time

if len(sys.argv) == 3:
    sys.path.insert(0,sys.argv[2])
    payload=Path(sys.argv[2])/'vendor/lscli'
else:
    import ls
    payload=Path(ls.__file__).parent/'_sdk_payload'
from ls.core.agent.sdk_imports import activate
finder=activate(payload)
from ls.core.agent.broker_rpc import Channel
from ls.core.agent.sdk_persistence import checkpoint_store
from ls.core.agent.sdk_iteration import iterate
from pydantic_ai.models.test import TestModel
from pydantic_ai_harness.step_persistence import ContinuableSnapshot
channel=Channel(socket.socket(fileno=int(sys.argv[1])),task='task',session='session',
                methods=frozenset({'checkpoint.save'}),expires=time.monotonic()+10)


async def main():
    store=checkpoint_store(finder,channel,run_id='run')
    async def emit(raw):pass
    result=await iterate(TestModel(call_tools=[],custom_output_text='durable fixture'),finder,
                         prompt='Answer fixture',instructions='No tools.',tools=(),store=store,on_event=emit,
                         check=lambda:None,expires=time.monotonic()+10,run_id='run',conversation_id='conversation')
    snapshot=await store.latest_snapshot(run_id='run')
    assert snapshot is not None and store.last_checkpoint
    digest=store.last_checkpoint
    channel.close()
    try:await store.save_snapshot(ContinuableSnapshot(run_id='run',step_index=99,messages=[]))
    except ConnectionError:pass
    else:raise AssertionError('lost acknowledgement accepted')
    assert await store.latest_snapshot(run_id='run') is snapshot and store.last_checkpoint==digest
    class Replies:
        def __init__(self, replies): self.replies,self.closed,self.calls=iter(replies),False,0
        async def request_async(self,*args):
            self.calls+=1
            return next(self.replies)
        def close(self): self.closed=True
    replies=Replies([{'digest':'a'*64},{'digest':'b'*64},{'digest':'c'*64}])
    local=checkpoint_store(finder,replies,run_id='run')
    old=ContinuableSnapshot(run_id='run',step_index=0,messages=[],idempotency_key='1:0:complete')
    new=ContinuableSnapshot(run_id='run',step_index=1,messages=[],idempotency_key='2:1:complete')
    await local.save_snapshot(old);await local.save_snapshot(new);await local.save_snapshot(new);await local.save_snapshot(old)
    assert replies.calls==2 and local.last_checkpoint=='b'*64 and await local.latest_snapshot(run_id='run') is new
    malformed=Replies([{'digest':'bad'}])
    local=checkpoint_store(finder,malformed,run_id='run')
    try:await local.save_snapshot(old)
    except ValueError:pass
    else:raise AssertionError('malformed acknowledgement accepted')
    assert malformed.closed and local.last_checkpoint is None and await local.latest_snapshot(run_id='run') is None
    print(json.dumps({'digest':digest,'messages':result['messages'].decode(),'output':result['output'],
                      'lost_ack_not_promoted':True,'origins':finder.verify_origins()}))
asyncio.run(main())
