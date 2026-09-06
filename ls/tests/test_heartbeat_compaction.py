import json

import pytest

from ls.core.agent import heartbeat_compaction as compact
from ls.core.agent.runtime_install import _write_json
from ls.tests.test_heartbeat_process import run
from ls.tests.test_session_owner import state, own, broker
from ls.tests.test_checkpoint_store import save


def receipt(source='a'*64, checkpoint='b'*64):
    return dict(schema_version=1, source_checkpoint=source, checkpoint=checkpoint, profile='c'*64,
                usage=dict(requests=1, tool_calls=0, input_tokens=100, output_tokens=10))


def adapter():
    return compact.Receipt(source='a'*64, profile='c'*64, token_limit=200)


@pytest.mark.parametrize('returncode', [0, 2])
def test_real_process_requires_receipt_and_exit_agreement(tmp_path, returncode):
    value = receipt()
    code = 'import sys; print('+repr(json.dumps(value))+'); sys.exit('+str(returncode)+')'
    result = run(tmp_path, code, timeout=3, receipt=adapter())
    assert result['protocol']['completed'] is (returncode == 0)
    assert result['returncode'] == (0 if returncode == 0 else 1)
    assert result['stdout_tail'] == result['stderr_tail'] == ''


@pytest.mark.parametrize('bad', ['truncated', 'duplicate', 'second_object', 'source', 'profile', 'usage', 'same', 'large'])
def test_invalid_child_receipt_is_not_continuation(bad):
    value = receipt()
    if bad == 'source': value['source_checkpoint'] = 'd'*64
    elif bad == 'profile': value['profile'] = 'd'*64
    elif bad == 'usage': value['usage']['input_tokens'] = 201
    elif bad == 'same': value['checkpoint'] = value['source_checkpoint']
    raw = json.dumps(value).encode()
    if bad == 'truncated': raw = raw[:-1]
    elif bad == 'duplicate': raw = raw.replace(b'"schema_version": 1', b'"schema_version": 1, "schema_version": 1')
    elif bad == 'second_object': raw += b'{}'
    elif bad == 'large': raw += b' '*compact.LIMIT
    item = adapter()
    with pytest.raises(ValueError):
        item.feed(raw)
        item.finish(0)


def test_fragmented_receipt_is_not_activity_and_cannot_be_reused():
    item = adapter()
    raw = json.dumps(receipt()).encode()
    for byte in raw:
        assert item.feed(bytes([byte])) is False
    assert item.finish(0)['completed']
    with pytest.raises(ValueError): item.feed(b' ')
    with pytest.raises(ValueError): item.finish(0)


@pytest.mark.parametrize('bad', [None, 'missing', 'public', 'symlink', 'mismatch', 'bool_schema', 'unsettled', 'uncertain'])
def test_continuation_requires_real_owner_receipt_and_settled_history(state, broker, bad):
    with own(state, broker) as owner:
        source = save(owner, profile='c'*64)
        target = save(owner, profile='c'*64, run_id='compact', state='interrupted' if bad == 'unsettled' else 'complete')
        value = receipt(source, target)
        path = owner.root/('compaction-'+target+'.json')
        if bad != 'missing': _write_json(path, value if bad != 'mismatch' else receipt(source, 'd'*64))
        if bad == 'bool_schema': _write_json(path, dict(value, schema_version=True))
        if bad == 'public': path.chmod(0o644)
        elif bad == 'symlink':
            original = path.with_name('original.json')
            path.rename(original)
            path.symlink_to(original)
        elif bad == 'uncertain':
            owner._journal.begin('process', dict(argv_sha256='a'*64, snapshot_sha256='b'*64))
        if bad is None:
            assert compact.verify(owner, value, source=source, profile='c'*64, token_limit=200) == target
            assert owner.resume_checkpoint(source, profile='c'*64) == b'[]'
        else:
            with pytest.raises((ValueError, OSError, PermissionError)):
                compact.verify(owner, value, source=source, profile='c'*64, token_limit=200)


@pytest.mark.parametrize('child', ['checkpoints', 'journal'])
def test_verification_does_not_recreate_missing_coordination_lock(state, broker, child):
    with own(state, broker) as owner:
        source = save(owner, profile='c'*64)
        target = save(owner, profile='c'*64, run_id='compact')
        value = receipt(source, target)
        _write_json(owner.root/('compaction-'+target+'.json'), value)
        lock = owner.root/child/compact.LOCK_NAME
        lock.unlink()
        with pytest.raises(FileNotFoundError):
            compact.verify(owner, value, source=source, profile='c'*64, token_limit=200)
        assert not lock.exists()
