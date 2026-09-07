import json
from pathlib import Path
import socket
import threading
import time

import pytest
from ls.core.agent.broker_rpc import Channel
from ls.core.agent.supervisor import supervise


def test_supervisor_services_broker_on_owning_thread(tmp_path):
    left,right=socket.socketpair();deadline=time.monotonic()+3
    channel=Channel(left,task='task',session='session',methods=frozenset({'read'}),expires=deadline)
    owner=threading.get_ident();calls=[]
    def handler(method,data):
        assert threading.get_ident()==owner
        calls.append(data)
        return {'answer':42}
    script="""import socket,sys,json,struct
s=socket.socket(fileno=int(sys.argv[1]))
raw=json.dumps({'schema_version':1,'task':'task','session':'session','sequence':0,'type':'request','method':'read','data':{}}).encode()
s.sendall(struct.pack('!I',len(raw))+raw)
size=struct.unpack('!I',s.recv(4))[0]
response=json.loads(s.recv(size));print(json.dumps(response))
s.close()
"""
    try:
        outcome=supervise(['/usr/bin/python3','-I','-B','-c',script,str(right.fileno())],b'',cwd=tmp_path,
                          environment={},timeout=2,capture=True,pass_fds=(right.fileno(),),broker=(channel,handler,lambda:None))
        assert outcome.status=='completed' and len(calls)==1
        assert json.loads(outcome.data['stdout'])['data']=={'answer':42}
    finally:channel.close();right.close()


def test_broker_contract_refused_before_launch(tmp_path):
    with pytest.raises(ValueError,match='channel'):
        supervise(['/usr/bin/true'],b'',cwd=tmp_path,environment={},timeout=1,broker=(None,None,None))


def test_cancellation_interrupts_partial_broker_frame(tmp_path):
    left,right=socket.socketpair();cancel=threading.Event()
    channel=Channel(left,task='task',session='session',methods=frozenset({'read'}),expires=time.monotonic()+30)
    code="import socket,sys,time;s=socket.socket(fileno=int(sys.argv[1]));s.sendall(b'xx');time.sleep(30)"
    timer=threading.Timer(.1,cancel.set);timer.start();start=time.monotonic()
    try:
        outcome=supervise(['/usr/bin/python3','-I','-B','-c',code,str(right.fileno())],b'',cwd=tmp_path,environment={},
                          timeout=2,cancel=cancel,pass_fds=(right.fileno(),),broker=(channel,lambda *a:pytest.fail('must not dispatch'),lambda:None))
        assert outcome.status=='cancelled' and outcome.data is None
        assert time.monotonic()-start<1
    finally:timer.cancel();timer.join();channel.close();right.close()


def test_partial_frame_worker_exit_does_not_wait_for_retained_peer(tmp_path):
    left,right=socket.socketpair()
    channel=Channel(left,task='task',session='session',methods=frozenset({'read'}),expires=time.monotonic()+30)
    code="import socket,sys,time;s=socket.socket(fileno=int(sys.argv[1]));s.sendall(b'xx');time.sleep(.05)"
    start=time.monotonic()
    try:
        with pytest.raises(ConnectionError):
            supervise(['/usr/bin/python3','-I','-B','-c',code,str(right.fileno())],b'',cwd=tmp_path,environment={},
                      timeout=10,pass_fds=(right.fileno(),),broker=(channel,lambda *a:pytest.fail('must not dispatch'),lambda:None))
        assert time.monotonic()-start<1
    finally:channel.close();right.close()
