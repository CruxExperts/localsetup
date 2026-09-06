"""Task-bound tool-free completion through a protected, supervised SDK worker."""
import hashlib
import math
import re
import socket
import time

from .broker_rpc import Channel,_encode,_decode
from .completion_contract import EXITS,MAX_REQUEST,MAX_OUTPUT
from .profiles import parse
from .runtime_install import selected
from .supervisor import supervise

METHODS=frozenset({'complete.start','complete.finish'})


def identity(payload):
    if not isinstance(payload,dict) or set(payload)!={'profile','credential','request'}:
        raise ValueError('Invalid completion payload')
    parse(payload['profile'])
    if not isinstance(payload['credential'],str) or not isinstance(payload['request'],str) or len(payload['request'].encode())>MAX_REQUEST:
        raise ValueError('Invalid completion payload values')
    return hashlib.sha256(_encode({k:v for k,v in payload.items() if k!='credential'})).hexdigest()


def accept(value,model):
    fields={'interface_version','status','data','model','usage','request_id','attempts','reason'}
    if not isinstance(value,dict) or set(value)!=fields or type(value['interface_version']) is not int or value['interface_version']!=1:
        raise ValueError('Invalid completion result envelope')
    status=value['status']
    if not isinstance(status,str) or status not in EXITS or value['reason']!=status or value['model']!=model:
        raise ValueError('Completion outcome identity differs')
    if type(value['attempts']) is not int or value['attempts'] not in (0,1) or (status=='succeeded' and value['attempts']!=1):
        raise ValueError('Invalid completion attempt count')
    if status!='succeeded' and value['data'] is not None:raise ValueError('Failure result contains data')
    usage=value['usage']
    if usage is not None and (not isinstance(usage,dict) or set(usage)!={'input_tokens','output_tokens'} or any(type(n) is not int or not 0<=n<=10**12 for n in usage.values())):
        raise ValueError('Invalid completion usage')
    identifier=value['request_id']
    if identifier is not None and (not isinstance(identifier,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,256}',identifier)):
        raise ValueError('Invalid completion request identifier')
    if len(_encode(value))>MAX_OUTPUT+4096:raise ValueError('Completion outcome exceeds limit')


class Handler:
    def __init__(self,payload,check):
        self.payload=_decode(_encode(payload));self.digest=identity(self.payload)
        self.check=check;self.started=False;self.result=None

    def __call__(self,method,data):
        self.check()
        if self.result is not None:raise ValueError('Completion exchange finished')
        if method=='complete.start' and data=={} and not self.started:
            self.started=True
            return {'input_sha256':self.digest,'payload':self.payload}
        if method!='complete.finish' or not self.started or not isinstance(data,dict) or set(data)!={'input_sha256','result'} or data['input_sha256']!=self.digest:
            raise ValueError('Invalid completion exchange')
        accept(data['result'],self.payload['profile']['model'])
        self.check();self.result=_decode(_encode(data['result']))
        return {'result_sha256':hashlib.sha256(_encode(self.result)).hexdigest()}


def run(runtimes,payload,authority,*,expected_release=None):
    started=time.monotonic();payload=_decode(_encode(payload));digest=identity(payload);expires=authority.expires
    try:
        value=_decode(payload['request'].encode());seconds=value.get('deadline_seconds') if isinstance(value,dict) else None
        if type(seconds) in (int,float) and math.isfinite(seconds) and 0<seconds<=3600:
            expires=min(expires,started+seconds)
    except (ValueError,RecursionError):pass
    def current():
        authority.check(digest)
        if time.monotonic()>=expires:raise TimeoutError('Completion deadline expired')
    current();handler=Handler(payload,current)
    with selected(runtimes,timeout=max(0,expires-time.monotonic())) as release:
        if expected_release is not None and release.resolve()!=expected_release.resolve():
            raise PermissionError('Completion runtime changed')
        left,right=socket.socketpair();channel=None
        try:
            channel=Channel(left,task=authority.task,session=authority.session,methods=METHODS,expires=expires,cancelled=authority.revoked)
            current()
            outcome=supervise([str(release/'venv/bin/python'),'-I','-B','-m','ls.core.agent.completion_worker',str(right.fileno()),authority.task,authority.session,str(expires)],b'',cwd=release,
                environment={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'},timeout=max(0,expires-time.monotonic()),cancel=authority.revoked,capture=True,pass_fds=(right.fileno(),),broker=(channel,handler,current))
            if outcome.status!='completed' or handler.result is None:
                raise RuntimeError('Completion worker did not complete')
            receipt={'result_sha256':hashlib.sha256(_encode(handler.result)).hexdigest()}
            if _decode(outcome.data['stdout'])!=receipt:raise ValueError('Completion process receipt differs')
            current();return handler.result
        finally:
            if channel is not None:channel.close()
            else:left.close()
            right.close()
