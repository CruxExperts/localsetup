"""Exact-authority compaction with supervised receipts and immutable checkpoints."""
import hashlib
from pathlib import Path
import socket
import time
import uuid

from .broker_rpc import Channel,_encode,_decode
from .checkpoint_store import MAX_MESSAGES
from .coding_protocol import profile_digest
from .runtime_install import selected,_write_json
from .session_owner import _separate,_Revocation
from .supervisor import supervise

METHODS=frozenset({'compact.start','compact.finish'})


def request(payload):
    from .profiles import parse
    fields={'schema_version','profile','credential','history','keep_messages','token_limit'}
    if not isinstance(payload,dict) or set(payload)!=fields or type(payload['schema_version']) is not int or payload['schema_version']!=1:
        raise ValueError('Invalid compaction request')
    profile=parse(payload['profile'])
    if 'streaming' not in profile.capabilities:
        raise ValueError('Compaction requires a qualified streaming profile')
    if not isinstance(payload['credential'],str):raise ValueError('Explicit compaction credential required')
    profile.credential({profile.credential_env:payload['credential']})
    if not isinstance(payload['history'],str) or len(payload['history'].encode())>MAX_MESSAGES:
        raise ValueError('Invalid compaction history')
    if type(payload['keep_messages']) is not int or not 0<=payload['keep_messages']<=256 or type(payload['token_limit']) is not int or not 1<=payload['token_limit']<=1000000:
        raise ValueError('Invalid compaction limits')
    return hashlib.sha256(_encode({k:v for k,v in payload.items() if k!='credential'})).hexdigest()


class Handler:
    def __init__(self,payload,check):
        self.payload=_decode(_encode(payload));self.digest=request(self.payload)
        self.check=check;self.started=False;self.result=None

    def __call__(self,method,data):
        self.check()
        if self.result is not None:raise ValueError('Compaction exchange finished')
        if method=='compact.start' and data=={} and not self.started:
            self.started=True
            return {'input_sha256':self.digest,'payload':self.payload}
        if method!='compact.finish' or not self.started or not isinstance(data,dict) or set(data)!={'input_sha256','messages','summary','usage'} or data['input_sha256']!=self.digest:
            raise ValueError('Invalid compaction result exchange')
        from .compaction_content import accept,usage
        accept(self.payload['history'],data['messages'],data['summary'],keep_messages=self.payload['keep_messages'])
        usage(data['usage'],self.payload['token_limit'])
        self.check();self.result=_decode(_encode(data))
        return {'messages_sha256':hashlib.sha256(data['messages'].encode()).hexdigest(),'usage':data['usage']}


def compact_checkpoint(owner,runtimes,checkpoint,payload,authority,*,expected_release=None):
    payload=_decode(_encode(payload));digest=request(payload);authority.check(digest)
    if (authority.task,authority.session)!=(owner._journal.task,owner._journal.session):
        raise PermissionError('Compaction authority belongs to another session')
    profile=profile_digest(payload['profile'])
    if owner.resume_checkpoint(checkpoint,profile=profile).decode()!=payload['history']:
        raise PermissionError('Compaction history differs from current checkpoint')
    _separate(owner.root.parent,runtimes)
    def current():
        authority.check(digest);owner._check()
        if owner.resume_checkpoint(checkpoint,profile=profile).decode()!=payload['history']:
            raise PermissionError('Compaction source changed')
    revoked=_Revocation(owner.revoked,authority.revoked)
    handler=Handler(payload,current)
    expires=min(owner.expires,authority.expires)
    with selected(runtimes,timeout=max(0,expires-time.monotonic())) as release:
        if expected_release is not None and release.resolve()!=expected_release.resolve():
            raise PermissionError('Protected runtime changed before compaction')
        left,right=socket.socketpair();channel=None
        try:
            channel=Channel(left,task=authority.task,session=authority.session,methods=METHODS,expires=expires,cancelled=revoked)
            current()
            outcome=supervise([str(release/'venv/bin/python'),'-I','-B','-m','ls.core.agent.compaction_worker',str(right.fileno()),authority.task,authority.session,str(expires)],b'',cwd=release,
                environment={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'},timeout=max(0,expires-time.monotonic()),cancel=revoked,capture=True,pass_fds=(right.fileno(),),broker=(channel,handler,current))
            if outcome.status!='completed' or handler.result is None:raise RuntimeError('Compaction worker did not complete')
            result=handler.result
            receipt={'messages_sha256':hashlib.sha256(result['messages'].encode()).hexdigest(),'usage':result['usage']}
            if _decode(outcome.data['stdout'])!=receipt:raise ValueError('Compaction process receipt differs')
            current()
        finally:
            if channel is not None:channel.close()
            else:left.close()
            right.close()
    current()
    saved=owner.save_checkpoint(result['messages'].encode(),profile=profile,run_id=uuid.uuid4().hex,step=0,state='complete')
    receipt={'schema_version':1,'source_checkpoint':checkpoint,'checkpoint':saved,'profile':profile,'usage':result['usage']}
    _write_json(owner.root/('compaction-'+saved+'.json'),receipt)
    current();owner.resume_checkpoint(saved,profile=profile)
    return receipt
