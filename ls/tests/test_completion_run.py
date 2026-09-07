import hashlib,time
from contextlib import contextmanager
from types import SimpleNamespace
import pytest
from ls.core.agent import completion_run as run
from ls.core.agent.broker_rpc import _encode
from ls.core.agent.completion_contract import envelope
from ls.core.agent.coding_run import CodingGrant


def payload():
    return {'profile':{'base_url':'https://fixture.invalid/v1/','api':'responses','model':'fixture','credential_env':'KEY','timeout_seconds':5,'capabilities':[],'allow_loopback_http':False},'credential':'fixture','request':'{}'}


def test_completion_handler_rejects_injection_and_repeated_exchange():
    value=payload();handler=run.Handler(value,lambda:None)
    with pytest.raises(ValueError):handler('complete.finish',{'input_sha256':handler.digest,'result':envelope('succeeded',model='fixture',attempts=1)})
    assert handler.result is None
    request=handler('complete.start',{})
    result=envelope('succeeded',model='fixture',data={'ok':True},attempts=1)
    for change in [{'model':'other'},{'reason':'secret'},{'attempts':True},{'usage':{'input_tokens':-1,'output_tokens':0}},{'request_id':'\nsecret'},{'unexpected':1}]:
        with pytest.raises(ValueError):handler('complete.finish',{'input_sha256':request['input_sha256'],'result':result|change})
    ack=handler('complete.finish',{'input_sha256':request['input_sha256'],'result':result})
    assert ack=={'result_sha256':hashlib.sha256(_encode(result)).hexdigest()}
    with pytest.raises(ValueError):handler('complete.start',{})


@pytest.mark.parametrize('case',['success','bad_receipt','failed_process','revoke','timeout'])
def test_completion_requires_current_authority_and_process_receipt(tmp_path,monkeypatch,case):
    value=payload();grant=CodingGrant('task','session',run.identity(value),time.monotonic()+5)
    @contextmanager
    def selected(*args,**kwargs):yield tmp_path
    monkeypatch.setattr(run,'selected',selected)
    result=envelope('succeeded',model='fixture',data={'ok':True},attempts=1)
    def supervise(*args,**kwargs):
        _,handler,check=kwargs['broker'];check()
        request=handler('complete.start',{})
        ack=handler('complete.finish',{'input_sha256':request['input_sha256'],'result':result})
        if case=='revoke':grant.revoked.set()
        return SimpleNamespace(status='timed_out' if case=='timeout' else 'failed' if case=='failed_process' else 'completed',data={'stdout':_encode({} if case=='bad_receipt' else ack).decode()})
    monkeypatch.setattr(run,'supervise',supervise)
    if case=='success':assert run.run(tmp_path,value,grant)==result
    elif case=='timeout':
        with pytest.raises(TimeoutError):run.run(tmp_path,value,grant)
    else:
        with pytest.raises((ValueError,RuntimeError,PermissionError)):run.run(tmp_path,value,grant)


def test_completion_freezes_authorized_payload(tmp_path,monkeypatch):
    import threading
    value=payload();digest=run.identity(value)
    def check(actual):
        assert actual==digest
        value['request']='{"input":"substituted"}'
    grant=SimpleNamespace(task='task',session='session',expires=time.monotonic()+5,revoked=threading.Event(),check=check)
    @contextmanager
    def selected(*args,**kwargs):yield tmp_path
    monkeypatch.setattr(run,'selected',selected)
    result=envelope('invalid_request',model='fixture')
    def supervise(*args,**kwargs):
        _,handler,current=kwargs['broker'];current()
        request=handler('complete.start',{})
        assert request['payload']['request']=='{}' and request['input_sha256']==digest
        ack=handler('complete.finish',{'input_sha256':digest,'result':result})
        return SimpleNamespace(status='completed',data={'stdout':_encode(ack).decode()})
    monkeypatch.setattr(run,'supervise',supervise)
    assert run.run(tmp_path,value,grant)==result
