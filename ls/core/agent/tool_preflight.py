"""Provider-free qualification of one leased runtime and explicit tool environment."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field, replace
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time

from .process_broker import run
from .resource_group import Limits
from .runtime_install import selected
from .runtime_lock import _directory
from .sandbox import ProcessGrant
from .session_owner import _separate

NAMESPACES=('mnt','net','pid','user')
_PROBE="""import errno,json,os,socket
from pathlib import Path
assert Path('input').read_bytes()==b'preflight'
for path in ('/inputs/input','/root-write-probe'):
 try:Path(path).write_bytes(b'no')
 except OSError as e:assert e.errno==errno.EROFS
 else:raise AssertionError('writable protected mount')
assert not Path('/sys/fs/cgroup').exists()
print(json.dumps({'schema':1,'namespaces':{n:os.stat('/proc/self/ns/'+n).st_ino for n in ('mnt','net','pid','user')},
 'capacity':{p:os.statvfs(p).f_blocks*os.statvfs(p).f_frsize for p in ('/work','/tmp')},
 'network':[name for index,name in socket.if_nameindex()]}))
"""


class _Revocation:
    def __init__(self,*events):
        self.events=events

    def is_set(self):
        return any(event.is_set() for event in self.events)


@dataclass(frozen=True)
class ToolQualification:
    task: str
    session: str
    release: Path
    resource_parent: Path
    limits: Limits
    expires: float
    revoked: threading.Event
    _closed: threading.Event = field(default_factory=threading.Event,repr=False)

    def check(self, task, session):
        if (self._closed.is_set() or self.revoked.is_set() or time.monotonic()>=self.expires
                or task!=self.task or session!=self.session):
            raise PermissionError('Tool qualification is inactive, expired or mismatched')

    def bind(self, grant: ProcessGrant):
        """Apply qualified resource settings to a freshly authorized process grant."""
        self.check(grant.task,grant.session)
        grant.check(self.task,self.session)
        if grant.work_bytes>512*1024*1024 or grant.temporary_bytes>64*1024*1024:
            raise ValueError('Process storage exceeds qualified capacities')
        return replace(grant,resource_parent=self.resource_parent,limits=self.limits,
                       expires=min(grant.expires,self.expires),
                       revoked=_Revocation(grant.revoked,self.revoked,self._closed))

    def run(self, grant: ProcessGrant, *, provider=False, cancel=None):
        return run(self.release.parent,self.bind(grant),task=self.task,session=self.session,
                   provider=provider,cancel=cancel)


def _validate(data, host):
    if not isinstance(data,dict) or set(data)!={'schema','namespaces','capacity','network'} or type(data['schema']) is not int or data['schema']!=1:
        raise ValueError('Invalid sandbox preflight response')
    namespaces=data['namespaces']
    if not isinstance(namespaces,dict) or set(namespaces)!=set(NAMESPACES) or any(
            type(value) is not int or value<=0 or value==host[name] for name,value in namespaces.items()):
        raise ValueError('Sandbox namespace isolation is not qualified')
    if data['network'] not in ([],['lo']):
        raise ValueError('Sandbox network isolation is not qualified')
    capacity=data['capacity']
    if not isinstance(capacity,dict) or set(capacity)!={'/work','/tmp'} or any(
            type(value) is not int or value<=0 or value>limit for value,limit in
            ((capacity['/work'],512*1024*1024),(capacity['/tmp'],64*1024*1024))):
        raise ValueError('Sandbox storage capacity is not qualified')


@contextmanager
def qualified_tools(runtimes: Path, scratch: Path, resource_parent: Path, *, task: str,
                    session: str, expires: float, limits: Limits, revoked=None):
    """Run before provider dispatch; keep the context open while using this result."""
    if not isinstance(resource_parent,Path) or not resource_parent.is_absolute() or not isinstance(limits,Limits):
        raise ValueError('Tool preflight requires explicit delegation and limits')
    if not isinstance(task,str) or not task or not isinstance(session,str) or not session or not math.isfinite(expires):
        raise ValueError('Tool preflight requires task/session identity and deadline')
    revoked=revoked if revoked is not None else threading.Event()
    if revoked.is_set() or time.monotonic()>=expires:
        raise PermissionError('Tool preflight is revoked or expired')
    for boundary in (runtimes,Path('/usr'),resource_parent):
        _separate(scratch,boundary)
    fd=_directory(scratch)
    try:
        if os.fstat(fd).st_mode&0o077:
            raise ValueError('Tool preflight scratch must be private')
    finally:
        os.close(fd)
    with selected(runtimes,timeout=max(0,expires-time.monotonic())) as release:
        qualification=ToolQualification(task,session,release,resource_parent,limits,expires,revoked)
        try:
            host={name:os.stat('/proc/self/ns/'+name).st_ino for name in NAMESPACES}
            with tempfile.TemporaryDirectory(prefix='tool-probe-',dir=scratch) as temporary:
                stage=Path(temporary)
                with (stage/'input').open('xb') as stream:
                    os.fchmod(stream.fileno(),0o600);stream.write(b'preflight')
                grant=ProcessGrant(task,session,stage,('/usr/bin/python3','-I','-B','-c',_PROBE),
                                   min(expires,time.monotonic()+15),revoked=revoked,
                                   resource_parent=resource_parent,limits=limits)
                outcome=run(runtimes,grant,task=task,session=session)
                if outcome.status!='completed' or outcome.returncode!=0 or not isinstance(outcome.data,dict) or set(outcome.data)!={'stdout','stderr'} or outcome.data['stderr']:
                    raise RuntimeError('Tool sandbox preflight failed; no provider dispatch is permitted')
                if not isinstance(outcome.data['stdout'],str) or len(outcome.data['stdout'])>4096:
                    raise ValueError('Sandbox preflight response exceeds limit')
                _validate(json.loads(outcome.data['stdout']),host)
                if (stage/'input').read_bytes()!=b'preflight':
                    raise RuntimeError('Sandbox preflight modified host input')
            qualification.check(task,session)
            yield qualification
        finally:
            qualification._closed.set()
