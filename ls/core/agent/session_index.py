"""Bounded metadata inventory using existing session locks; never creates state."""
from __future__ import annotations

import fcntl
import hashlib
import os
from pathlib import Path
import stat
import time

from .broker_rpc import _decode
from .operation_journal import DIGEST, IDENTIFIER, Journal
from .runtime_lock import LOCK_NAME, _directory


def _file(directory, name):
    fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1 or info.st_mode & 0o7077:
            raise ValueError('Session metadata must be private owned regular files')
        return fd
    except BaseException:
        os.close(fd);raise


def _one(root, name, check):
    directory=_directory(root/name)
    lock=None
    try:
        if os.fstat(directory).st_mode & 0o077:
            raise ValueError('Session directory must be private')
        lock=_file(directory,LOCK_NAME)
        try:fcntl.flock(lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
        except BlockingIOError:return {'storage_id':name,'status':'busy'}
        opened=os.fstat(lock);current=os.stat(LOCK_NAME,dir_fd=directory,follow_symlinks=False)
        if (opened.st_dev,opened.st_ino)!=(current.st_dev,current.st_ino):
            raise ValueError('Session lock identity changed')
        fd=_file(directory,'identity.json')
        try:raw=os.read(fd,16385)
        finally:os.close(fd)
        if len(raw)>16384:raise ValueError('Session identity exceeds limit')
        value=_decode(raw)
        if not isinstance(value,dict) or set(value)!={'schema_version','task','session','workspace_sha256'} or type(value['schema_version']) is not int or value['schema_version']!=1:
            raise ValueError('Invalid session identity schema')
        if any(not isinstance(value[k],str) or not IDENTIFIER.fullmatch(value[k]) for k in ('task','session')) or not isinstance(value['workspace_sha256'],str) or not DIGEST.fullmatch(value['workspace_sha256']):
            raise ValueError('Invalid session identity')
        if hashlib.sha256(value['session'].encode()).hexdigest()!=name:
            raise ValueError('Session storage identity mismatch')
        journal=Journal(root/name/'journal',task=value['task'],session=value['session'])
        fd=_directory(journal.root)
        try:
            if os.fstat(fd).st_mode & 0o077:raise ValueError('Journal must be private')
            records,_,_=journal._load(fd,check=check)
        finally:os.close(fd)
        states=journal._states(records)
        current=os.stat(root/name,follow_symlinks=False);opened=os.fstat(directory)
        if (opened.st_dev,opened.st_ino)!=(current.st_dev,current.st_ino):
            raise ValueError('Session directory identity changed')
        check()
        return {'storage_id':name,'task':value['task'],'session':value['session'],
                'status':'uncertain' if any(x['outcome']=='uncertain' for x in states.values()) else 'settled',
                'operation_count':len(states)}
    finally:
        if lock is not None:os.close(lock)
        os.close(directory)


def scan(root: Path, *, expires: float):
    root=root.absolute()
    try:directory=_directory(root)
    except FileNotFoundError:return {'schema_version':1,'sessions':[],'ignored_entries':0}
    try:
        if os.fstat(directory).st_mode & 0o077:raise ValueError('Session inventory must be private')
        names=os.listdir(directory)
    finally:os.close(directory)
    if len(names)>1000:raise ValueError('Session inventory exceeds 1000 entries')
    result=[];ignored=0
    def check():
        if time.monotonic()>=expires:raise TimeoutError('Session inventory deadline expired')
    for name in sorted(names):
        check()
        if not DIGEST.fullmatch(name):
            ignored+=1;continue
        try:result.append(_one(root,name,check))
        except TimeoutError:raise
        except (OSError,ValueError,TypeError,RecursionError):result.append({'storage_id':name,'status':'invalid'})
    return {'schema_version':1,'sessions':result,'ignored_entries':ignored}
