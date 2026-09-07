"""Durable local tool receipts joined to settled operation evidence, never authority."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time

from .checkpoint_store import Checkpoints, MAX_COUNT, MAX_TOTAL, _read
from .operation_journal import DIGEST, IDENTIFIER
from .runtime_lock import LOCK_NAME, runtime_use
from .session_owner import _private

MAX_RESULT = 4 * 1024 * 1024


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _validate(value):
    required = {'schema_version', 'task', 'session', 'profile', 'checkpoint', 'tool_call', 'result'}
    if not isinstance(value, dict) or set(value) != required or type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ValueError('Invalid tool result schema')
    if any(not isinstance(value[k], str) or not IDENTIFIER.fullmatch(value[k]) for k in ('task', 'session')):
        raise ValueError('Invalid tool result identity')
    if any(not isinstance(value[k], str) or not DIGEST.fullmatch(value[k]) for k in ('profile', 'checkpoint')):
        raise ValueError('Invalid tool result evidence digest')
    call = value['tool_call']
    if not isinstance(call, dict) or set(call) != {'run_id', 'call_id', 'name', 'arguments_sha256'}:
        raise ValueError('Invalid tool result call schema')
    if any(not isinstance(call[k], str) or not IDENTIFIER.fullmatch(call[k]) for k in ('run_id', 'call_id', 'name')) or not isinstance(call['arguments_sha256'], str) or not DIGEST.fullmatch(call['arguments_sha256']):
        raise ValueError('Invalid tool result call identity')
    result = value['result']
    if not isinstance(result, dict) or set(result) not in ({'operation', 'status'}, {'operation', 'status', 'returncode', 'output'}):
        raise ValueError('Invalid tool result payload')
    if not isinstance(result['operation'], str) or not re.fullmatch(r'[0-9a-f]{32}', result['operation']):
        raise ValueError('Invalid tool result operation')
    if len(json.dumps(value, allow_nan=False).encode()) > MAX_RESULT:
        raise ValueError('Tool result exceeds 4 MiB limit')


def _join(owner, value, states):
    """Called only while the owning session operation is held."""
    _validate(value)
    if (value['task'], value['session']) != (owner._journal.task, owner._journal.session):
        raise PermissionError('Tool result belongs to another session')
    result = value['result']
    state = states.get(result['operation'])
    if state is None or state['outcome'] == 'uncertain' or state['outcome'] != result['status']:
        raise PermissionError('Tool result requires the matching settled operation')
    intent = state['intent']
    if intent.get('checkpoint') != value['checkpoint'] or intent.get('tool_call') != value['tool_call']:
        raise PermissionError('Tool result differs from operation call evidence')
    # A pre-tool checkpoint is deliberately behind the current frontier. Identity
    # is checked here; this receipt alone cannot make that history resumable.
    checkpoint = owner._checkpoints().load(value['checkpoint'], timeout=max(0, owner.expires-time.monotonic()))
    if (checkpoint['task'], checkpoint['session'], checkpoint['profile'], checkpoint['run_id']) != (
            value['task'], value['session'], value['profile'], value['tool_call']['run_id']):
        raise PermissionError('Tool result checkpoint identity differs')
    if intent['kind'] == 'file_replace':
        if set(result) != {'operation', 'status'} or result['status'] not in ('applied', 'not_applied') or value['tool_call']['name'] != 'write_file':
            raise ValueError('Invalid settled file result')
    elif intent['kind'] == 'process':
        if set(result) != {'operation', 'status', 'returncode', 'output'} or value['tool_call']['name'] != 'run_command':
            raise ValueError('Invalid settled process result')
        if _digest({'status': result['status'], 'returncode': result['returncode'], 'data': result['output']}) != state['result']['evidence_sha256']:
            raise PermissionError('Process output differs from settled evidence')
    else:
        raise ValueError('Unsupported tool result kind')
    owner._check()


def _store(owner, *, create):
    root = owner.root/'tool-results'
    if create:
        fd = _private(owner.root)
        try:
            try:
                os.mkdir('tool-results', mode=0o700, dir_fd=fd)
            except FileExistsError:
                pass
            os.fsync(fd)
        finally:
            os.close(fd)
    return Checkpoints(root, validate=_validate)


def save(owner, result, *, profile, checkpoint, tool_call):
    """Internal: caller holds owner._operation(); flush before RPC acknowledgement."""
    value = json.loads(json.dumps({'schema_version': 1, 'task': owner._journal.task,
        'session': owner._journal.session, 'profile': profile, 'checkpoint': checkpoint,
        'tool_call': tool_call, 'result': result}, allow_nan=False))
    states = owner._journal.inspect(timeout=max(0, owner.expires-time.monotonic()))
    _join(owner, value, states)
    digest = _store(owner, create=True).save(value, timeout=max(0, owner.expires-time.monotonic()))
    owner._check()
    return digest


def recover(owner, operation, *, profile):
    """Read local evidence under fresh session authority; does not disclose or replay."""
    if not isinstance(operation, str) or not re.fullmatch(r'[0-9a-f]{32}', operation):
        raise ValueError('Invalid recovery operation')
    with owner._operation(recovery=True) as states:
        store = _store(owner, create=False)
        found, total = None, 0
        with runtime_use(store.root, timeout=max(0, owner.expires-time.monotonic())):
            directory = _private(store.root)
            try:
                names = [name for name in os.listdir(directory) if name != LOCK_NAME]
                if len(names) > MAX_COUNT:
                    raise ValueError('Tool result count limit exceeded')
                for name in names:
                    owner._check()
                    if re.fullmatch(r'\.pending-[0-9a-f]{32}', name):
                        continue  # Never accept an interrupted uncommitted write.
                    raw, value = _read(directory, name, _validate)
                    total += len(raw)
                    if total > MAX_TOTAL:
                        raise ValueError('Tool result storage exceeds byte limit')
                    if value['result']['operation'] == operation:
                        if found is not None:
                            raise ValueError('Conflicting durable tool results')
                        _join(owner, value, states)
                        if value['profile'] != profile:
                            raise PermissionError('Tool result requires a compatible profile')
                        found = value
            finally:
                os.close(directory)
        owner._check()
        if found is None:
            raise FileNotFoundError('No durable tool result; do not replay the operation')
        return found
