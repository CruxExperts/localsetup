from dataclasses import replace
import threading

import pytest

from ls.core.agent.file_broker import FileBroker
from ls.core.agent.file_rpc import FileHandler
from ls.core.agent.nested_context import candidates
from ls.tests.test_session_owner import state,own,broker


def test_ordered_refresh_observes_changed_nested_instructions(state,broker):
    root=broker.grant.root;(root/'AGENTS.md').write_text('root rules');(root/'src/AGENTS.md').write_text('nested rules')
    allowed=FileBroker(replace(broker.grant,read=('.',),disclose=('.',)),broker.lease_root)
    with own(state,broker) as owner:
        handler=FileHandler(owner,allowed,profile='a'*64,run_id='run')
        first=handler('context.refresh',{'directory':'src/deeper'})
        assert [x['path'] for x in first['resources']]==['AGENTS.md','src/AGENTS.md']
        assert first['missing']==['src/deeper/AGENTS.md']
        (root/'src/AGENTS.md').write_text('new nested rules')
        second=handler('context.refresh',{'directory':'src'})
        assert second['resources'][1]['content']=='new nested rules'
        assert second['resources'][1]['sha256']!=first['resources'][1]['sha256'] and owner.inspect()=={}


def test_missing_does_not_bypass_disclosure_and_symlinks_refused(state,broker):
    root=broker.grant.root
    with own(state,broker) as owner:
        handler=FileHandler(owner,FileBroker(replace(broker.grant,disclose=('src',)),broker.lease_root),profile='a'*64,run_id='run')
        with pytest.raises(PermissionError):handler('context.refresh',{'directory':'src'})
        handler.broker=FileBroker(replace(broker.grant,read=('.',),disclose=('.',)),broker.lease_root)
        (root/'AGENTS.md').symlink_to('src/a.txt')
        with pytest.raises(OSError):handler('context.refresh',{'directory':'src'})
    with pytest.raises(ValueError):candidates('/'.join(['x']*16))


def test_disclosure_revoked_after_encoding_refuses(state,broker,monkeypatch):
    from ls.core.agent import nested_context
    revoked=threading.Event()
    allowed=FileBroker(replace(broker.grant,read=('.',),disclose=('.',),revoked=revoked),broker.lease_root)
    encode=nested_context._encode
    def changed(value):
        raw=encode(value);revoked.set();return raw
    monkeypatch.setattr(nested_context,'_encode',changed)
    with own(state,broker) as owner:
        handler=FileHandler(owner,allowed,profile='a'*64,run_id='run')
        with pytest.raises(PermissionError,match='revoked'):handler('context.refresh',{'directory':'src'})
        owner._check()
