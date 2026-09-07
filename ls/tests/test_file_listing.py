from dataclasses import replace
import os

import pytest

from ls.core.agent.file_broker import FileBroker
from ls.core.agent.file_rpc import FileHandler
from ls.tests.test_session_owner import state,own,broker


def test_directory_scope_and_unsafe_entries(state,broker):
    root=broker.grant.root
    (root/'src/sub').mkdir();(root/'src/.env').write_text('private')
    (root/'src/link').symlink_to('a.txt');os.mkfifo(root/'src/pipe')
    with own(state,broker) as owner:
        allowed=FileBroker(replace(broker.grant,disclose=('src',)),broker.lease_root)
        handler=FileHandler(owner,allowed,profile='a'*64,run_id='run')
        result=handler('file.list',{'path':'src'})
        assert result=={'path':'src','entries':[{'path':'src/a.txt','kind':'file'},{'path':'src/sub','kind':'directory'}],'truncated':False}
        with pytest.raises(PermissionError):handler('file.list',{'path':'.'})
        handler.broker=FileBroker(replace(allowed.grant,read=('.',),disclose=('.',)),broker.lease_root)
        assert handler('file.list',{'path':'.'})['entries']==[{'path':'src','kind':'directory'}]
        assert owner.inspect()=={}


def test_file_only_or_missing_disclosure_refuses_listing(state,broker):
    with own(state,broker) as owner:
        for read,disclose in [(('src/a.txt',),('src',)),(('src',),()),(('.',),('src/a.txt',))]:
            handler=FileHandler(owner,FileBroker(replace(broker.grant,read=read,disclose=disclose),broker.lease_root),profile='a'*64,run_id='run')
            with pytest.raises(PermissionError):handler('file.list',{'path':'src'})
        (broker.grant.root/'linked').symlink_to('src')
        handler=FileHandler(owner,FileBroker(replace(broker.grant,read=('.',),disclose=('.',)),broker.lease_root),profile='a'*64,run_id='run')
        with pytest.raises(OSError):handler('file.list',{'path':'linked'})


def test_complete_envelope_bound_with_long_selected_path(state,broker,monkeypatch):
    from ls.core.agent import file_listing
    from ls.core.agent.broker_rpc import _encode
    name='src/'+'/'.join(['directory-name']*20)
    directory=broker.grant.root/name;directory.mkdir(parents=True)
    for number in range(5):(directory/f'file-{number}').write_text('x')
    monkeypatch.setattr(file_listing,'MAX_RESULT',1024)
    with own(state,broker) as owner:
        allowed=FileBroker(replace(broker.grant,disclose=('src',)),broker.lease_root)
        handler=FileHandler(owner,allowed,profile='a'*64,run_id='run')
        result=handler('file.list',{'path':name})
        assert result['truncated'] and 0<len(result['entries'])<5
        assert len(_encode(result))<=1024
        monkeypatch.setattr(file_listing,'MAX_RESULT',100)
        with pytest.raises(ValueError,match='metadata'):handler('file.list',{'path':name})
