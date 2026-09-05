import hashlib
from pathlib import Path
import time

from ls.core.agent.session_index import scan
from ls.tests.test_session_owner import state, own, broker


def test_listing_missing_state_creates_nothing(tmp_path):
    root=tmp_path/'absent'
    assert scan(root,expires=time.monotonic()+1)['sessions']==[]
    assert not root.exists()


def test_listing_settled_busy_uncertain_and_invalid_without_content(state,broker):
    with own(state,broker) as owner:
        assert scan(state,expires=time.monotonic()+1)['sessions'][0]['status']=='busy'
    report=scan(state,expires=time.monotonic()+1)
    assert report['sessions'][0]['task']=='task' and report['sessions'][0]['operation_count']==0
    with own(state,broker) as owner:
        owner._journal.begin('process',{'argv_sha256':'a'*64,'snapshot_sha256':'b'*64})
    assert scan(state,expires=time.monotonic()+1)['sessions'][0]['status']=='uncertain'
    root=state/hashlib.sha256(b'session').hexdigest()
    (root/'identity.json').write_text('{broken')
    before={str(p.relative_to(state)):p.read_bytes() for p in state.rglob('*') if p.is_file()}
    assert scan(state,expires=time.monotonic()+1)['sessions'][0]['status']=='invalid'
    assert before=={str(p.relative_to(state)):p.read_bytes() for p in state.rglob('*') if p.is_file()}


def test_custom_entries_ignored_and_symlink_sessions_never_followed(state,tmp_path):
    (state/'custom').write_text('preserve')
    (state/('f'*64)).symlink_to(tmp_path,target_is_directory=True)
    report=scan(state,expires=time.monotonic()+1)
    assert report['ignored_entries']==1 and report['sessions']==[{'storage_id':'f'*64,'status':'invalid'}]
    assert (state/'custom').read_text()=='preserve'


def test_nested_corrupt_identity_does_not_hide_valid_neighbor(state,broker):
    from ls.core.agent.runtime_lock import LOCK_NAME
    with own(state,broker):pass
    damaged=state/('f'*64);damaged.mkdir(mode=0o700)
    for name,text in [(LOCK_NAME,''),('identity.json','['*1500+'0'+']'*1500)]:
        path=damaged/name;path.write_text(text);path.chmod(0o600)
    report=scan(state,expires=time.monotonic()+1)
    assert {item['status'] for item in report['sessions']}=={'settled','invalid'}
    assert any(item.get('session')=='session' for item in report['sessions'])


def test_session_cli_full_stderr_failure_is_bounded(state):
    import os
    from ls.core.agent.cli import main
    state.chmod(0o755)
    read,write=os.pipe();saved=os.dup(2)
    try:
        os.set_blocking(write,False)
        while True:
            try:os.write(write,b'x'*4096)
            except BlockingIOError:break
        os.set_blocking(write,True);os.dup2(write,2)
        start=time.monotonic()
        assert main(['sessions','--state-root',str(state.parent)])==2
        assert time.monotonic()-start<1 and os.get_blocking(write)
    finally:
        os.dup2(saved,2)
        for fd in (read,write,saved):os.close(fd)
