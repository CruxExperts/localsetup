"""A lost acknowledgement must preserve evidence without another tool dispatch."""
import hashlib
import json

import pytest

from ls.core.agent.file_rpc import FileHandler
from ls.core.agent.tool_results import recover, save, _digest
from ls.tests.test_session_owner import state, own, broker


def write(owner, broker):
    checkpoint = owner.save_checkpoint(b'[]', profile='a'*64, run_id='run', step=0, state='interrupted')
    data = {'path':'src/a.txt', 'content':'changed', 'expected_before':hashlib.sha256(b'original').hexdigest(),
            'checkpoint':checkpoint, 'call_id':'write'}
    return FileHandler(owner, broker, profile='a'*64, run_id='run')('file.write', data)


def test_lost_file_ack_recovered_by_fresh_owner_without_write(state, broker):
    with own(state, broker) as owner:
        result = write(owner, broker)
    # Change the workspace afterwards: recovery describes recorded history only.
    target = broker.grant.root/'src/a.txt'
    target.write_bytes(b'later edit')
    with own(state, broker) as owner:
        receipt = recover(owner, result['operation'], profile='a'*64)
        assert receipt['result'] == result
        assert len(owner.inspect()) == 1
        with pytest.raises(PermissionError, match='stale'):
            owner.resume_checkpoint(receipt['checkpoint'], profile='a'*64)
        with pytest.raises(PermissionError, match='compatible'):
            recover(owner, result['operation'], profile='b'*64)
    assert target.read_bytes() == b'later edit'


def test_receipt_failure_after_effect_never_acknowledged_or_replayed(state, broker, monkeypatch):
    from ls.core.agent import tool_results
    def fail(*args, **kwargs):
        raise OSError('simulated storage failure')
    with own(state, broker) as owner:
        original = tool_results.save
        monkeypatch.setattr(tool_results, 'save', fail)
        with pytest.raises(OSError, match='storage failure'):
            write(owner, broker)
        operation, = owner.inspect()
        assert owner.inspect()[operation]['outcome'] == 'applied'
        monkeypatch.setattr(tool_results, 'save', original)
        with pytest.raises(FileNotFoundError):
            recover(owner, operation, profile='a'*64)
    assert (broker.grant.root/'src/a.txt').read_bytes() == b'changed'


def test_process_output_join_and_missing_receipt_refuse_fabrication(state, broker):
    with own(state, broker) as owner:
        checkpoint = owner.save_checkpoint(b'[]', profile='a'*64, run_id='run', step=0, state='interrupted')
        call = {'run_id':'run', 'call_id':'command', 'name':'run_command', 'arguments_sha256':'b'*64}
        with owner._operation():
            operation = owner._journal.begin('process', {'argv_sha256':'b'*64, 'snapshot_sha256':'c'*64}, checkpoint=checkpoint, tool_call=call)
            output = {'stdout':'test passed', 'stderr':''}
            owner._journal.finish(operation, 'completed', evidence_sha256=_digest({'status':'completed', 'returncode':0, 'data':output}))
            result = {'operation':operation, 'status':'completed', 'returncode':0, 'output':output}
            with pytest.raises(PermissionError, match='differs from settled'):
                save(owner, result|{'output':{'stdout':'invented', 'stderr':''}}, profile='a'*64, checkpoint=checkpoint, tool_call=call)
            save(owner, result, profile='a'*64, checkpoint=checkpoint, tool_call=call)
        assert recover(owner, operation, profile='a'*64)['result'] == result
        with pytest.raises(FileNotFoundError, match='do not replay'):
            recover(owner, 'f'*32, profile='a'*64)
        # A damaged persisted record cannot be accepted despite valid journal data.
        path, = (owner.root/'tool-results').glob('*.json')
        value = json.loads(path.read_text()); value['result']['output']['stdout'] = 'forged'
        path.write_text(json.dumps(value))
        with pytest.raises(ValueError, match='digest mismatch'):
            recover(owner, operation, profile='a'*64)


def test_revoked_owner_cannot_read_recovery_content(state, broker):
    with own(state, broker) as owner:
        result = write(owner, broker)
    with pytest.raises(PermissionError, match='closed'):
        recover(owner, result['operation'], profile='a'*64)
