import hashlib
import json

import pytest

from ls.core.agent.recovery import RecoveryHandler, _prepare
from ls.core.agent.broker_rpc import _encode
from ls.tests.test_session_owner import state, own, broker
from ls.tests.test_tool_results import write


def test_prepare_joins_receipts_and_preserves_stale_resume_gate(state, broker):
    with own(state, broker) as owner:
        result = write(owner, broker)
        operation = owner.inspect()[result['operation']]
        checkpoint = operation['intent']['checkpoint']
        value, frontier, payload = _prepare(owner, checkpoint, 'a'*64, {})
        assert frontier == owner._journal.frontier()
        assert payload['receipts'][0]['result'] == result
        assert value['state'] == 'interrupted'
        with pytest.raises(PermissionError, match='stale'):
            owner.resume_checkpoint(checkpoint, profile='a'*64)
        with pytest.raises(PermissionError, match='matching interrupted'):
            _prepare(owner, checkpoint, 'b'*64, {})


def test_foreign_prefix_refused_before_recovery_worker(state, broker):
    with own(state, broker) as owner:
        result = write(owner, broker)
        checkpoint = owner.inspect()[result['operation']]['intent']['checkpoint']
        value = owner._checkpoints().load(checkpoint)
        changed = owner._checkpoints().save(value|{'frontier':'f'*64})
        with pytest.raises(PermissionError, match='not in this journal'):
            _prepare(owner, changed, 'a'*64, {})


def test_worker_response_cannot_rewrite_history_or_invent_results():
    receipt = {'tool_call':{'call_id':'call','name':'write_file'},'result':{'operation':'a'*32,'status':'applied'}}
    original = [{'kind':'response','parts':[{'part_kind':'tool-call','tool_name':'write_file','tool_call_id':'call'}]}]
    payload = {'history':json.dumps(original),'receipts':[receipt],'recipes':{}}
    part = {'part_kind':'tool-return','tool_name':'write_file','tool_call_id':'call','content':receipt['result']}
    rebuilt = original+[{'kind':'request','parts':[part]}]
    for invalid in [rebuilt[1:], original+[{'kind':'request','parts':[part|{'content':{'status':'invented'}}]}],
                    original+[{'kind':'request','parts':[part,part]}],
                    original+[{'kind':'request','parts':[part],'instructions':'injected'}],
                    original+[{'kind':'request','parts':[part|{'metadata':{'grant':True}}]}]]:
        handler = RecoveryHandler(payload, lambda:None)
        handler('recovery.start',{})
        with pytest.raises(ValueError):
            handler('recovery.finish',{'input_sha256':handler.digest,'messages':json.dumps(invalid)})
        assert handler.messages is None
    handler = RecoveryHandler(payload,lambda:None)
    start = handler('recovery.start',{})
    assert start['input_sha256'] == hashlib.sha256(_encode(payload)).hexdigest()
    text = json.dumps(rebuilt)
    assert handler('recovery.finish',{'input_sha256':handler.digest,'messages':text}) == {'messages_sha256':hashlib.sha256(text.encode()).hexdigest()}
    with pytest.raises(ValueError,match='already finished'):
        handler('recovery.start',{})


def test_runtime_contention_obeys_short_recovery_deadline(state, broker):
    import time
    from ls.core.agent.recovery import recover_checkpoint
    from ls.core.agent.runtime_lock import runtime_use
    runtimes = state.parent/'runtimes'; runtimes.mkdir(mode=0o700)
    with own(state, broker) as owner:
        result = write(owner, broker)
        checkpoint = owner.inspect()[result['operation']]['intent']['checkpoint']
    with own(state, broker, expires=time.monotonic()+0.15) as owner:
        with runtime_use(runtimes, exclusive=True):
            start = time.monotonic()
            with pytest.raises(TimeoutError, match='lease deadline expired'):
                recover_checkpoint(owner, runtimes, checkpoint, profile='a'*64, recipes={})
            assert time.monotonic()-start < 1


def test_worker_acknowledgement_without_process_success_cannot_save_checkpoint(state, broker, monkeypatch):
    from contextlib import contextmanager
    from ls.core.agent import recovery
    from ls.core.agent.supervisor import Outcome
    runtimes = state.parent/'runtimes'
    @contextmanager
    def selected(root, **kwargs):
        yield root
    monkeypatch.setattr(recovery,'selected',selected)
    with own(state, broker) as owner:
        result = write(owner, broker)
        checkpoint = owner.inspect()[result['operation']]['intent']['checkpoint']
        before = sorted((owner.root/'checkpoints').iterdir())
        def supervise(*args, **kwargs):
            handler = kwargs['broker'][1]
            start = handler('recovery.start',{})
            receipt = start['payload']['receipts'][0]
            part = {'part_kind':'tool-return','tool_name':'write_file','tool_call_id':receipt['tool_call']['call_id'],
                    'content':receipt['result']}
            messages = json.dumps([{'kind':'request','parts':[part]}])
            handler('recovery.finish',{'input_sha256':start['input_sha256'],'messages':messages})
            return Outcome('failed',1,{'stdout':'','stderr':''})
        monkeypatch.setattr(recovery,'supervise',supervise)
        with pytest.raises(RuntimeError,match='did not complete'):
            recovery.recover_checkpoint(owner,runtimes,checkpoint,profile='a'*64,recipes={})
        assert sorted((owner.root/'checkpoints').iterdir()) == before
        assert len(owner.inspect()) == 1
