import hashlib
import os
from pathlib import Path

import pytest

from ls.core.agent.checkpoint_store import Checkpoints
from ls.core.agent import checkpoint_store
from ls.tests.test_session_owner import state, own, broker


def save(owner, **kwargs):
    return owner.save_checkpoint(b'[]', **(dict(profile='a'*64, run_id='run', step=0, state='complete') | kwargs))


def test_checkpoint_round_trip_identity_and_operation_join(state, broker):
    with own(state, broker) as owner:
        checkpoint = save(owner)
        assert save(owner) == checkpoint
        assert owner.resume_checkpoint(checkpoint, profile='a'*64) == b'[]'
        operation = owner.write(broker,'src/a.txt',b'changed',expected_before=hashlib.sha256(b'original').hexdigest(),checkpoint=checkpoint)
        assert owner.inspect()[operation]['intent']['checkpoint'] == checkpoint
        with pytest.raises(PermissionError, match='stale'):
            owner.resume_checkpoint(checkpoint, profile='a'*64)
        latest = save(owner, step=1)
    with own(state, broker) as resumed:
        assert resumed.resume_checkpoint(latest, profile='a'*64) == b'[]'
        with pytest.raises(PermissionError, match='compatible'):
            resumed.resume_checkpoint(latest, profile='b'*64)


def test_interrupted_checkpoint_never_resumes_or_hides_uncertainty(state, broker):
    with own(state, broker) as owner:
        interrupted = save(owner, state='interrupted')
        with pytest.raises(PermissionError, match='settled'):
            owner.resume_checkpoint(interrupted, profile='a'*64)
        owner._journal.begin('process', {'argv_sha256':'a'*64,'snapshot_sha256':'b'*64})
        with pytest.raises(PermissionError, match='complete checkpoint'):
            save(owner)
        saved = save(owner, step=1, state='interrupted')
        with pytest.raises(PermissionError, match='reconciliation'):
            owner.resume_checkpoint(saved, profile='a'*64)


def test_stale_checkpoint_blocks_dispatch_before_mutation(state, broker):
    with own(state, broker) as owner:
        old = save(owner)
        owner.write(broker,'src/a.txt',b'changed',expected_before=hashlib.sha256(b'original').hexdigest())
        with pytest.raises(PermissionError, match='stale'):
            owner.write(broker,'src/a.txt',b'bad',expected_before=hashlib.sha256(b'changed').hexdigest(),checkpoint=old)
    assert (broker.grant.root/'src/a.txt').read_bytes() == b'changed'


def test_replaced_or_corrupt_checkpoint_refused(state, broker):
    with own(state, broker) as owner:
        digest = save(owner)
        path = owner.root/'checkpoints'/f'{digest}.json'
        original = path.read_bytes()
        path.write_bytes(original+b' ')
        with pytest.raises(ValueError, match='digest'):
            owner.resume_checkpoint(digest, profile='a'*64)
        path.unlink(); path.symlink_to(broker.grant.root/'src/a.txt')
        with pytest.raises(OSError):
            owner.resume_checkpoint(digest, profile='a'*64)


def test_flush_failure_retains_record_without_acknowledgement(state, broker, monkeypatch):
    with own(state, broker) as owner:
        store = owner._checkpoints()
        original = os.fsync
        def flush(fd):
            original(fd)
            if Path(os.readlink(f'/proc/self/fd/{fd}')) == store.root:
                raise OSError('directory flush interrupted')
        with monkeypatch.context() as patch:
            patch.setattr(os,'fsync',flush)
            with pytest.raises(OSError): save(owner)
        records = list(store.root.glob('*.json'))
        assert len(records) == 1
        assert save(owner) == records[0].stem


def test_limits_and_authority_after_flush(state, broker, monkeypatch):
    with own(state, broker) as owner:
        first = save(owner)
        monkeypatch.setattr(checkpoint_store,'MAX_COUNT',1)
        with pytest.raises(ValueError, match='full'):
            save(owner, step=1)
        assert owner.resume_checkpoint(first, profile='a'*64) == b'[]'
        original = os.fsync
        def flush(fd):
            original(fd)
            if Path(os.readlink(f'/proc/self/fd/{fd}')) == owner.root/'checkpoints':
                owner._closed.set()
        monkeypatch.setattr(os,'fsync',flush)
        with pytest.raises(PermissionError, match='closed'):
            save(owner)


def test_pending_writes_consume_capacity_and_unknown_names_refuse(state, broker, monkeypatch):
    with own(state, broker) as owner:
        root = owner._checkpoints().root
        pending = root / ('.pending-'+'a'*32)
        pending.write_bytes(b'partial'); pending.chmod(0o600)
        monkeypatch.setattr(checkpoint_store, 'MAX_COUNT', 1)
        with pytest.raises(ValueError, match='full'):
            save(owner)
        pending.rename(root/'.pending-invalid')
        with pytest.raises(ValueError, match='digest'):
            save(owner)


def test_failed_parent_flush_is_retried_before_checkpoint_ack(state, broker, monkeypatch):
    with own(state, broker) as owner:
        original = os.fsync
        calls = []
        def flush(fd):
            path = Path(os.readlink(f'/proc/self/fd/{fd}'))
            if path == owner.root:
                calls.append(path)
                if len(calls) == 1:
                    raise OSError('parent flush failed')
            original(fd)
        monkeypatch.setattr(os, 'fsync', flush)
        with pytest.raises(OSError):
            save(owner)
        digest = save(owner)
        assert len(calls) == 2
        assert owner.resume_checkpoint(digest, profile='a'*64) == b'[]'


@pytest.mark.parametrize('boundary', ['session', 'journal'])
def test_session_directory_retry_reflushes_parent(state, broker, monkeypatch, boundary):
    root = state/hashlib.sha256(b'session').hexdigest()
    original, calls = os.fsync, []
    def flush(fd):
        path = Path(os.readlink(f'/proc/self/fd/{fd}'))
        relevant = path == state if boundary == 'session' else path == root and (root/'journal').exists()
        if relevant:
            calls.append(path)
            if len(calls) == 1:
                raise OSError('parent flush failed')
        original(fd)
    monkeypatch.setattr(os, 'fsync', flush)
    with pytest.raises(OSError):
        with own(state, broker): pass
    with own(state, broker):
        assert len(calls) >= 2
