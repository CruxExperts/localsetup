import hashlib
import json
from pathlib import Path
import stat
import time

import pytest

from ls.core.agent.file_broker import FileBroker
from ls.core.agent.file_grants import FileGrant
from ls.core.agent.snapshot import create


@pytest.fixture
def inputs(tmp_path):
    workspace, leases, snapshots = [tmp_path / n for n in ('workspace', 'leases', 'snapshots')]
    for root in (workspace, leases, snapshots):
        root.mkdir(mode=0o700)
    (workspace / 'src').mkdir()
    (workspace / 'src/run.py').write_text('print(42)')
    (workspace / 'src/run.py').chmod(0o755)
    (workspace / 'private').write_text('private')
    grant = FileGrant('task', 'session', workspace, ('.',), ('.',), ('src',), time.monotonic()+5)
    return FileBroker(grant, leases), snapshots


def test_snapshot_binds_hashes_modes_and_live_disclosure_authority(inputs):
    broker, root = inputs
    result = create(broker, root, ('src/run.py',), task='task', session='session', for_provider=True)
    copied = result.staging / 'src/run.py'
    assert copied.read_bytes() == b'print(42)'
    assert stat.S_IMODE(copied.stat().st_mode) == 0o700
    assert stat.S_IMODE(copied.parent.stat().st_mode) == 0o700
    assert not (result.staging / 'private').exists()
    record = json.loads(result.manifest.read_text())
    assert result.manifest.parent == result.staging.parent
    assert record['status'] == 'prepared'
    assert record['files'] == {'src/run.py': {'sha256': hashlib.sha256(b'print(42)').hexdigest(), 'size': 9, 'source_mode': 0o755}}
    process = result.process(('/usr/bin/python3', 'src/run.py'), expires=broker.grant.expires)
    assert process.disclose_output and process.revoked is broker.grant.revoked
    with pytest.raises(PermissionError, match='deadline'):
        result.process(('/usr/bin/true',), expires=broker.grant.expires+1)
    copied.write_text('changed in staging')
    assert (broker.grant.root / 'src/run.py').read_text() == 'print(42)'
    broker.grant.revoked.set()
    with pytest.raises(PermissionError):
        process.check('task', 'session')


def test_local_snapshot_does_not_grant_provider_disclosure(inputs):
    broker, root = inputs
    local = create(broker, root, ('private',), task='task', session='session')
    assert not local.process(('/usr/bin/true',), expires=broker.grant.expires).disclose_output
    before = set(root.iterdir())
    with pytest.raises(PermissionError, match='disclosure'):
        create(broker, root, ('private',), task='task', session='session', for_provider=True)
    assert set(root.iterdir()) == before


@pytest.mark.parametrize('names', [('AGENTS.md',), ('.env',), ('../outside',), ('src/run.py', 'src/run.py'), ('src', 'src/run.py')])
def test_invalid_inventory_precedes_allocation(inputs, names):
    broker, root = inputs
    with pytest.raises((ValueError, PermissionError)):
        create(broker, root, names, task='task', session='session')
    assert not list(root.iterdir())


def test_failed_projection_retains_incomplete_record_and_source(inputs):
    broker, root = inputs
    (broker.grant.root / 'src/link').symlink_to('run.py')
    with pytest.raises(OSError):
        create(broker, root, ('src/run.py', 'src/link'), task='task', session='session')
    container, = root.iterdir()
    assert json.loads((container / 'manifest.json').read_text())['status'] == 'incomplete'
    assert (broker.grant.root / 'src/run.py').read_text() == 'print(42)'


def test_shared_target_lease_covers_complete_projection(inputs, monkeypatch):
    from ls.core.agent.runtime_lock import runtime_use
    broker, root = inputs
    original = broker.read_entry
    def read(*args, **kwargs):
        with pytest.raises(TimeoutError):
            with runtime_use(broker.lease_root, exclusive=True, timeout=0):
                pass
        return original(*args, **kwargs)
    monkeypatch.setattr(broker, 'read_entry', read)
    create(broker, root, ('src/run.py',), task='task', session='session')


def test_workspace_and_shared_storage_refused(inputs):
    broker, root = inputs
    with pytest.raises(ValueError, match='separate'):
        create(broker, broker.grant.root, ('src/run.py',), task='task', session='session')
    root.chmod(0o755)
    with pytest.raises(ValueError, match='private'):
        create(broker, root, ('src/run.py',), task='task', session='session')


@pytest.mark.parametrize('action', ['revoke', 'expire'])
def test_authority_loss_during_directory_flush_leaves_incomplete(inputs, monkeypatch, action):
    from ls.core.agent import snapshot
    broker, root = inputs
    original = snapshot.os.fsync
    def flush(fd):
        original(fd)
        if Path(snapshot.os.readlink(f'/proc/self/fd/{fd}')).name == 'files':
            if action == 'revoke':
                broker.grant.revoked.set()
            else:
                monkeypatch.setattr(snapshot.time, 'monotonic', lambda: broker.grant.expires+1)
    monkeypatch.setattr(snapshot.os, 'fsync', flush)
    with pytest.raises(PermissionError):
        create(broker, root, ('src/run.py',), task='task', session='session')
    container, = root.iterdir()
    assert json.loads((container / 'manifest.json').read_text())['status'] == 'incomplete'
