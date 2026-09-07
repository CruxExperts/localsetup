import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import socket
import struct
import threading
import time

import pytest

from ls.core.agent import broker_rpc
from ls.core.agent.broker_rpc import Channel


@pytest.fixture
def pair():
    left,right = socket.socketpair()
    args = dict(task='task',session='session',methods=frozenset({'checkpoint'}),expires=time.monotonic()+2)
    client,server = Channel(left,**args),Channel(right,**args)
    yield client,server
    client.close();server.close()


def test_acknowledged_ordered_calls(pair):
    client,server = pair
    seen = []
    def handle(method,data):
        seen.append(data['value'])
        return {'value':data['value']+1}
    with ThreadPoolExecutor(1) as pool:
        for index in range(2):
            pending = pool.submit(client.request,'checkpoint',{'value':index})
            server.serve_once(handle,check=lambda:None)
            assert pending.result() == {'value':index+1}
    assert seen == [0,1] and client.sequence == server.sequence == 2


def test_mutation_without_ack_is_not_replayed(pair):
    client,server = pair
    seen = []
    def handle(method,data):
        seen.append('effect')
        raise OSError('private handler detail')
    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(client.request,'checkpoint',{})
        with pytest.raises(OSError): server.serve_once(handle,check=lambda:None)
        with pytest.raises(ConnectionError) as error: pending.result()
    assert 'private handler detail' not in str(error.value)
    with pytest.raises(ConnectionError): client.request('checkpoint',{})
    assert seen == ['effect']


@pytest.mark.parametrize('change',[{'sequence':1},{'sequence':True},{'task':'other'},{'method':'shell'},{'schema_version':True}])
def test_invalid_request_refuses_before_handler(pair,change):
    client,server = pair
    payload = client._envelope('request',{},'checkpoint') | change
    client._send(payload)
    seen = []
    with pytest.raises((ValueError,PermissionError)):
        server.serve_once(lambda *args:seen.append(True),check=lambda:None)
    assert not seen and server.closed


def test_oversized_incoming_frame_refused_without_body(pair):
    client,server = pair
    client.connection.sendall(struct.pack('!I',broker_rpc.MAX_FRAME+1))
    with pytest.raises(ValueError,match='limit'):
        server.serve_once(lambda *args:{},check=lambda:None)
    assert server.closed


def test_duplicate_json_refused(pair):
    client,server = pair
    raw=b'{"data":{},"data":{}}'
    client.connection.sendall(struct.pack('!I',len(raw))+raw)
    with pytest.raises(ValueError,match='Duplicate'):
        server.serve_once(lambda *args:{},check=lambda:None)


def test_deadline_cancel_and_reentrancy(pair):
    client,server = pair
    client.expires=time.monotonic()+.03
    with pytest.raises(TimeoutError): client.request('checkpoint',{})
    assert client.closed
    server.cancelled.set()
    with pytest.raises(ConnectionError): server.serve_once(lambda *args:{},check=lambda:None)


def test_reentrant_handler_refuses_second_exchange(pair):
    client,server = pair
    def handle(*args):
        with pytest.raises(RuntimeError,match='outstanding'):
            server.serve_once(handle,check=lambda:None)
        return {}
    with ThreadPoolExecutor(1) as pool:
        pending=pool.submit(client.request,'checkpoint',{})
        server.serve_once(handle,check=lambda:None)
        assert pending.result()=={}


def test_final_authority_refuses_ack(pair):
    client,server = pair
    checks=[]
    def check():
        checks.append(True)
        if len(checks)==2:raise PermissionError('revoked')
    with ThreadPoolExecutor(1) as pool:
        pending=pool.submit(client.request,'checkpoint',{})
        with pytest.raises(PermissionError):server.serve_once(lambda *args:{},check=check)
        with pytest.raises(ConnectionError):pending.result()


def test_async_cancellation_closes_channel(pair):
    client,server=pair
    async def run():
        task=asyncio.create_task(client.request_async('checkpoint',{}))
        await asyncio.sleep(.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
    asyncio.run(run())
    assert client.closed


def test_partial_frame_eof_does_not_dispatch(pair):
    client,server=pair
    client.connection.sendall(struct.pack('!I',100)+b'{')
    client.close()
    with pytest.raises(ConnectionError):
        server.serve_once(lambda *args:pytest.fail('partial request dispatched'),check=lambda:None)


def test_aggregate_and_call_count_limits(pair,monkeypatch):
    client,server=pair
    monkeypatch.setattr(broker_rpc,'MAX_BYTES',1)
    with pytest.raises(ValueError,match='aggregate'):
        client.request('checkpoint',{})
    monkeypatch.setattr(broker_rpc,'MAX_CALLS',0)
    with pytest.raises(ValueError,match='count'):
        server.serve_once(lambda *args:{},check=lambda:None)


def test_sequenced_packet_socket_is_not_a_stream():
    left,right=socket.socketpair(type=socket.SOCK_SEQPACKET)
    try:
        with pytest.raises(ValueError,match='stream'):
            Channel(left,task='task',session='session',methods=frozenset({'checkpoint'}),expires=time.monotonic()+1)
    finally:
        left.close();right.close()


def test_nested_numeric_overflow_refused_before_handler(pair):
    client,server=pair
    raw=b'{"schema_version":1,"task":"task","session":"session","sequence":0,"type":"request","method":"checkpoint","data":{"nested":[1e999]}}'
    client.connection.sendall(struct.pack('!I',len(raw))+raw)
    with pytest.raises(ValueError,match='Non-finite'):
        server.serve_once(lambda *args:pytest.fail('overflow dispatched'),check=lambda:None)


def test_deadline_after_result_validation_suppresses_ack(pair,monkeypatch):
    client,server=pair
    original=client._validate
    def validate(*args):
        original(*args)
        client.expires=time.monotonic()-1
    monkeypatch.setattr(client,'_validate',validate)
    with ThreadPoolExecutor(1) as pool:
        pending=pool.submit(client.request,'checkpoint',{})
        server.serve_once(lambda *args:{},check=lambda:None)
        with pytest.raises(TimeoutError):pending.result()
    assert client.closed
