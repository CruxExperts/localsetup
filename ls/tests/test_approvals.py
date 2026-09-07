import threading

import pytest

from ls.core.agent.approvals import Approvals


def decision(packet, **changes):
    return {'schema_version':1,'id':1,'method':'approve','task':'task','session':'session','profile':'profile',
            'challenge':packet['challenge'],'sha256':packet['sha256'],'allow':True}|changes


def gate():
    value=Approvals();value.bind('task','session','profile');return value


def test_concrete_preview_one_use_and_no_mutable_argument_substitution():
    value=gate();original={'path':'src/a'};seen=[]
    def emit(packet):
        seen.append(packet)
        assert packet['request']=={'method':'file.read','arguments':original}
        value.decide(decision(packet))
        with pytest.raises(PermissionError):value.decide(decision(packet))
        packet['request']['arguments']['path']='other'
        original['path']='changed'
    assert value.require('file.read',original,{},emit,lambda:None)=={'path':'src/a'}
    with pytest.raises(PermissionError):value.decide(decision(seen[0]))


def test_denial_foreign_and_revocation_after_decision_refuse():
    value=gate()
    def emit(packet):
        for changes in [{'task':'other'},{'sha256':'wrong'},{'challenge':'old'},{'allow':1}]:
            with pytest.raises(PermissionError):value.decide(decision(packet,**changes))
        value.decide(decision(packet,allow=False))
    with pytest.raises(PermissionError,match='denied'):value.require('file.read',{'path':'x'},{},emit,lambda:None)
    revoked=threading.Event()
    def check():
        if revoked.is_set():raise PermissionError('revoked')
    def accept(packet):value.decide(decision(packet));revoked.set()
    with pytest.raises(PermissionError,match='revoked'):value.require('file.read',{'path':'x'},{},accept,check)
    assert value.pending is None


def test_complete_preview_bounds_and_wait_checks():
    value=gate();emitted=[]
    with pytest.raises(ValueError):value.require('file.write',{'content':'x'*(128*1024)},{},emitted.append,lambda:None)
    assert not emitted
    calls=[]
    def check():
        calls.append(1)
        if len(calls)>1:raise TimeoutError('deadline')
    with pytest.raises(TimeoutError):value.require('file.read',{'path':'x'},{},emitted.append,check)
    assert value.pending is None


def test_worker_exit_ends_pending_approval_without_dispatch(tmp_path):
    import socket
    import time
    from ls.core.agent.broker_rpc import Channel
    from ls.core.agent.supervisor import supervise
    value=gate();left,right=socket.socketpair();requests=[];effects=[]
    channel=Channel(left,task='task',session='session',methods=frozenset({'file.read'}),expires=time.monotonic()+10)
    script="""import socket,sys,json,struct,time
s=socket.socket(fileno=int(sys.argv[1]))
raw=json.dumps({'schema_version':1,'task':'task','session':'session','sequence':0,'type':'request','method':'file.read','data':{'path':'x'}}).encode()
s.sendall(struct.pack('!I',len(raw))+raw)
time.sleep(.15)
"""
    def handler(method,data):
        approved=value.require(method,data,{},requests.append,channel._check)
        channel._check();effects.append(approved)
        return {}
    started=time.monotonic()
    try:
        with pytest.raises(ConnectionError):
            supervise(['/usr/bin/python3','-I','-B','-c',script,str(right.fileno())],b'',cwd=tmp_path,environment={},timeout=5,pass_fds=(right.fileno(),),broker=(channel,handler,lambda:None))
        assert time.monotonic()-started<1 and requests and not effects
        with pytest.raises(PermissionError):value.decide(decision(requests[0]))
    finally:channel.close();right.close()


@pytest.mark.parametrize('data',[{},[],{'directory':'.','extra':True}])
def test_malformed_context_approval_refuses_before_preview(data):
    value=gate();seen=[]
    with pytest.raises(ValueError):value.require('context.refresh',data,{},seen.append,lambda:None)
    assert seen==[] and value.pending is None
