"""Owned cgroup v2 resource limits under an explicitly delegated parent."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import stat
import time
import uuid


@dataclass(frozen=True)
class Limits:
    memory_bytes: int = 512 * 1024 * 1024
    tasks: int = 64
    cpu_percent: int = 100

    def __post_init__(self):
        for value, low, high in ((self.memory_bytes, 16*1024*1024, 16*1024**3),
                                 (self.tasks, 4, 512), (self.cpu_percent, 1, 800)):
            if type(value) is not int or not low <= value <= high:
                raise ValueError('Resource limits require bounded positive integers')

    def settings(self):
        return {'memory.max': str(self.memory_bytes), 'memory.swap.max': '0',
                'memory.oom.group': '1', 'pids.max': str(self.tasks),
                'cpu.max': f'{self.cpu_percent * 1000} 100000'}


def _read(fd, name):
    handle=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd)
    try:
        value=os.read(handle,4097)
        if len(value)>4096:
            raise ValueError('Oversized cgroup control value')
        return value.decode('ascii').strip()
    finally:
        os.close(handle)


def _write(fd, name, value):
    handle=os.open(name,os.O_WRONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd)
    try:
        data=value.encode('ascii')
        if os.write(handle,data)!=len(data):
            raise OSError('Incomplete cgroup control write')
    finally:
        os.close(handle)


def _parent(path):
    path=Path(path)
    root=Path('/sys/fs/cgroup')
    if not path.is_absolute() or '..' in path.parts or path==root or not path.is_relative_to(root):
        raise ValueError('Resource parent must be an explicit delegated cgroup')
    if any(p.is_symlink() for p in (path,*path.parents)):
        raise ValueError('Resource parent cannot contain symlinks')
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
    try:
        info=os.fstat(fd)
        if info.st_dev!=root.stat().st_dev or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)&0o022:
            raise PermissionError('Resource parent requires an owned cgroup2 delegation')
        if _read(fd,'cgroup.type')!='domain' or not {'cpu','memory','pids'} <= set(_read(fd,'cgroup.subtree_control').split()):
            raise RuntimeError('Delegation requires enabled cpu, memory and pids controllers')
        return fd
    except BaseException:
        os.close(fd)
        raise


class ResourceGroup:
    """A live membership descriptor; callers must keep all payloads sandboxed."""
    def __init__(self, fd, limits):
        self._fd,self.limits=fd,limits
        self._live=True

    def verify(self):
        if not self._live:
            raise RuntimeError('Resource group lease has ended')
        if any(_read(self._fd,key)!=value for key,value in self.limits.settings().items()):
            raise RuntimeError('Resource group limits changed')

    @contextmanager
    def membership(self):
        """Pass only to a trusted child which joins before dispatching its payload."""
        self.verify()
        fd=os.open('cgroup.procs',os.O_WRONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=self._fd)
        try:
            yield fd
        finally:
            os.close(fd)


def _drain(fd):
    _write(fd,'cgroup.kill','1')
    deadline=time.monotonic()+5
    while True:
        fields=dict(line.split() for line in _read(fd,'cgroup.events').splitlines())
        if fields.get('populated')=='0':
            return
        if time.monotonic()>=deadline:
            raise RuntimeError('Resource group still populated after kill; retain for recovery')
        time.sleep(0.01)


@contextmanager
def resource_group(parent: Path, limits: Limits):
    """Set and verify limits before yielding; kill/drain only this new child."""
    if not isinstance(limits,Limits):
        raise TypeError('Explicit resource limits required')
    parent_fd=_parent(parent)
    name='lscli-'+uuid.uuid4().hex
    fd=None
    group=None
    created=False
    try:
        os.mkdir(name,mode=0o700,dir_fd=parent_fd)
        created=True
        fd=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=parent_fd)
        for key,value in limits.settings().items():
            _write(fd,key,value)
        group=ResourceGroup(fd,limits)
        group.verify()
        # Require the kill interface before any child is allowed to join.
        _drain(fd)
        yield group
    finally:
        if group is not None:
            group._live=False
        try:
            if fd is not None:
                _drain(fd)
                os.rmdir(name,dir_fd=parent_fd)
            elif created:
                os.rmdir(name,dir_fd=parent_fd)
        finally:
            if fd is not None:
                os.close(fd)
            os.close(parent_fd)
