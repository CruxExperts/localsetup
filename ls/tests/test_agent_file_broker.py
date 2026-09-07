from dataclasses import replace
import os
from pathlib import Path
import time

import pytest

from ls.core.agent.file_grants import FileGrant
from ls.core.agent.file_broker import FileBroker
from ls.core.agent.runtime_lock import runtime_use


@pytest.fixture
def broker(tmp_path):
    root=tmp_path/'project';root.mkdir()
    lease=tmp_path/'leases';lease.mkdir(mode=0o700)
    (root/'src').mkdir();(root/'src/a.txt').write_bytes(b'original')
    grant=FileGrant('task','session',root,('src',),('src',),(),time.monotonic()+5)
    return FileBroker(grant,lease)


def test_authority_and_disclosure_are_separate(broker):
    assert broker.read('task','session','src/a.txt')==b'original'
    with pytest.raises(PermissionError,match='disclosure'):
        broker.read('task','session','src/a.txt',for_provider=True)
    allowed=FileBroker(replace(broker.grant,disclose=('src',)),broker.lease_root)
    assert allowed.read('task','session','src/a.txt',for_provider=True)==b'original'
    for task,session,name in [('other','session','src/a.txt'),('task','other','src/a.txt'),('task','session','outside')]:
        with pytest.raises(PermissionError):broker.read(task,session,name)


def test_atomic_write_preserves_mode_and_attributes(broker):
    path=broker.grant.root/'src/a.txt';path.chmod(0o750)
    os.setxattr(path,'user.fixture',b'preserve')
    inode=path.stat().st_ino
    broker.write('task','session','src/a.txt',b'replacement')
    assert path.read_bytes()==b'replacement' and path.stat().st_ino!=inode
    assert path.stat().st_mode&0o777==0o750
    assert os.getxattr(path,'user.fixture')==b'preserve'
    broker.write('task','session','src/new.txt',b'new')
    assert (path.parent/'new.txt').read_bytes()==b'new'
    assert not list(path.parent.glob('.lscli-write-*'))


@pytest.mark.parametrize('name',['../escape','/tmp/escape','src/../a','src//a','src/.git/config','src/.env','src/AGENTS.md'])
def test_unsafe_and_protected_writes_refused(broker,name):
    with pytest.raises(PermissionError):broker.write('task','session',name,b'bad')


def test_symlinks_and_hardlinks_refused(broker,tmp_path):
    root=broker.grant.root
    outside=tmp_path/'outside';outside.write_bytes(b'private')
    (root/'src/link').symlink_to(outside)
    (root/'src/dir').symlink_to(tmp_path,target_is_directory=True)
    os.link(outside,root/'src/hard')
    for name in ('src/link','src/dir/outside','src/hard'):
        with pytest.raises((OSError,PermissionError)):broker.read('task','session',name)
        with pytest.raises((OSError,PermissionError)):broker.write('task','session',name,b'bad')
    assert outside.read_bytes()==b'private'


def test_revocation_deadline_and_lease(broker):
    expired=FileBroker(replace(broker.grant,expires=time.monotonic()-1),broker.lease_root)
    with pytest.raises(PermissionError):expired.write('task','session','src/a.txt',b'bad')
    short=FileBroker(replace(broker.grant,expires=time.monotonic()+.03),broker.lease_root)
    with runtime_use(broker.lease_root):
        with pytest.raises(TimeoutError):short.write('task','session','src/a.txt',b'bad')
    broker.grant.revoked.set()
    with pytest.raises(PermissionError):broker.read('task','session','src/a.txt')


def test_revocation_during_write_preserves_target(broker,monkeypatch):
    original=os.fsync
    def revoke(fd):
        original(fd);broker.grant.revoked.set()
    monkeypatch.setattr(os,'fsync',revoke)
    with pytest.raises(PermissionError):broker.write('task','session','src/a.txt',b'bad')
    assert (broker.grant.root/'src/a.txt').read_bytes()==b'original'
    assert not list((broker.grant.root/'src').glob('.lscli-write-*'))


def test_changed_read_is_not_returned(broker,monkeypatch):
    original=os.read
    changed=[False]
    def mutate(fd,size):
        data=original(fd,size)
        if data and not changed[0]:
            changed[0]=True
            (broker.grant.root/'src/a.txt').write_bytes(b'changed')
        return data
    monkeypatch.setattr(os,'read',mutate)
    with pytest.raises(PermissionError,match='changed during read'):
        broker.read('task','session','src/a.txt')


def test_oversized_write_preserves_original(broker):
    with pytest.raises(ValueError,match='8 MiB'):
        broker.write('task','session','src/a.txt',b'x'*(8*1024*1024+1))
    assert (broker.grant.root/'src/a.txt').read_bytes()==b'original'


def test_protected_grant_root_and_mutable_scopes_refused(broker):
    with pytest.raises(ValueError,match='protected'):
        replace(broker.grant,root=broker.grant.root/'.git')
    with pytest.raises(ValueError,match='immutable'):
        replace(broker.grant,read=['src'])
