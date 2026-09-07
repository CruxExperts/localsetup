from dataclasses import replace

import pytest

from ls.core.agent.file_broker import FileBroker
from ls.core.agent.file_rpc import FileHandler
from ls.tests.test_session_owner import state, own, broker


def test_search_exact_lines_hashes_and_no_mutations(state,broker):
    allowed=FileBroker(replace(broker.grant,disclose=('src',)),broker.lease_root)
    (broker.grant.root/'src/a.txt').write_text('original\nother ORIGINAL\noriginal again\n')
    with own(state,broker) as owner:
        handler=FileHandler(owner,allowed,profile='a'*64,run_id='run')
        result=handler('file.search',{'paths':['src/a.txt'],'text':'original'})
        assert [m['line'] for m in result['matches']]==[1,3]
        assert result['matches'][0]['text']=='original' and not result['truncated']
        assert len(result['files'][0]['sha256'])==64 and owner.inspect()=={}


def test_search_disclosure_symlink_and_bounds(state,broker):
    with own(state,broker) as owner:
        handler=FileHandler(owner,broker,profile='a'*64,run_id='run')
        with pytest.raises(PermissionError,match='disclosure'):handler('file.search',{'paths':['src/a.txt'],'text':'original'})
        handler.broker=FileBroker(replace(broker.grant,disclose=('src',)),broker.lease_root)
        (broker.grant.root/'src/link').symlink_to('a.txt')
        with pytest.raises(OSError):handler('file.search',{'paths':['src/link'],'text':'original'})
        (broker.grant.root/'src/a.txt').write_text(('x'*600+'\n')*101)
        result=handler('file.search',{'paths':['src/a.txt'],'text':'x'})
        assert len(result['matches'])==100 and result['truncated']
        assert all(m['text_truncated'] and len(m['text'])==512 for m in result['matches'])
        for invalid in [{'paths':['src/a.txt']*2,'text':'x'},{'paths':['../escape'],'text':'x'},{'paths':['src/a.txt'],'text':'x\ny'}]:
            with pytest.raises((ValueError,PermissionError)):handler('file.search',invalid)


@pytest.mark.parametrize('lines',[1,101])
def test_narrower_disclosure_revocation_during_result_construction(state,broker,monkeypatch,lines):
    import threading
    from ls.core.agent import file_search
    revoked=threading.Event()
    allowed=FileBroker(replace(broker.grant,disclose=('src',),revoked=revoked),broker.lease_root)
    (broker.grant.root/'src/a.txt').write_text('original\n'*lines)
    encode=file_search._encode
    def revoke(value):
        result=encode(value)
        if isinstance(value,dict) and 'text_truncated' in value:revoked.set()
        return result
    monkeypatch.setattr(file_search,'_encode',revoke)
    with own(state,broker) as owner:
        handler=FileHandler(owner,allowed,profile='a'*64,run_id='run')
        with pytest.raises(PermissionError,match='revoked'):handler('file.search',{'paths':['src/a.txt'],'text':'original'})
        owner._check()  # The narrower file grant ended while session authority remained live.
