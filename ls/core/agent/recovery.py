"""Fresh-owner recovery joins durable evidence before accepting rebuilt SDK history."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import socket
import time

from .broker_rpc import Channel, _encode, _decode
from .checkpoint_store import MAX_MESSAGES
from .process_rpc import Recipe
from .runtime_install import selected
from .session_owner import _separate
from .supervisor import supervise
from .tool_results import recover

METHODS = frozenset({'recovery.start', 'recovery.finish'})


def _prepare(owner, checkpoint, profile, recipes):
    with owner._operation():
        value = owner._checkpoints().load(checkpoint, timeout=max(0, owner.expires-time.monotonic()))
        if (value['task'], value['session'], value['profile'], value['state']) != (
                owner._journal.task, owner._journal.session, profile, 'interrupted'):
            raise PermissionError('Recovery requires a matching interrupted checkpoint')
        suffix = owner._journal.after(value['frontier'], timeout=max(0, owner.expires-time.monotonic()))
        if not suffix['operations']:
            raise ValueError('Recovery checkpoint has no subsequent operations')
    receipts = []
    for operation, state in suffix['operations'].items():
        receipt = recover(owner, operation, profile=profile)
        if receipt['tool_call']['run_id'] != value['run_id']:
            raise PermissionError('Recovery suffix belongs to another run')
        receipts.append(receipt)
    if not isinstance(recipes, dict) or len(recipes) > 64 or any(not isinstance(k, str) or not isinstance(v, Recipe) for k, v in recipes.items()):
        raise ValueError('Recovery requires explicit validated recipes')
    payload = {'history': value['messages'], 'receipts': receipts,
               'recipes': {key: {'command': recipe.command, 'files': recipe.files, 'seconds': recipe.seconds}
                           for key, recipe in recipes.items()}}
    # Own a detached request before dispatch; transport size bounds also apply.
    payload = _decode(_encode(payload))
    owner._check()
    return value, suffix['frontier'], payload


class RecoveryHandler:
    def __init__(self, payload, check):
        self.payload = _decode(_encode(payload))
        self.digest = hashlib.sha256(_encode(self.payload)).hexdigest()
        self.check = check
        self.started, self.messages = False, None

    def __call__(self, method, data):
        self.check()
        if self.messages is not None:
            raise ValueError('Recovery exchange already finished')
        if method == 'recovery.start' and data == {} and not self.started:
            self.started = True
            return {'input_sha256': self.digest, 'payload': self.payload}
        if method != 'recovery.finish' or not self.started or not isinstance(data, dict) or set(data) != {'input_sha256', 'messages'} or data['input_sha256'] != self.digest:
            raise ValueError('Invalid recovery exchange')
        raw = data['messages']
        if not isinstance(raw, str) or len(raw.encode()) > MAX_MESSAGES:
            raise ValueError('Recovered history exceeds byte limit')
        original, rebuilt = _decode(self.payload['history']), _decode(raw)
        if not isinstance(rebuilt, list) or len(rebuilt) != len(original)+1 or _encode(rebuilt[:-1]) != _encode(original):
            raise ValueError('Recovery changed original message history')
        last = rebuilt[-1]
        expected = {r['tool_call']['call_id']: r for r in self.payload['receipts']}
        if not isinstance(last, dict) or last.get('kind') != 'request' or not isinstance(last.get('parts'), list) or len(last['parts']) != len(expected):
            raise ValueError('Recovery requires exactly the settled tool returns')
        defaults = {'kind':'request', 'timestamp':None, 'instructions':None, 'run_id':None,
                    'conversation_id':None, 'metadata':None, 'state':'complete'}
        if any(key != 'parts' and (key not in defaults or item != defaults[key]) for key, item in last.items()):
            raise ValueError('Recovery cannot add instructions or request metadata')
        seen = set()
        for part in last['parts']:
            if not isinstance(part, dict) or not isinstance(part.get('tool_call_id'), str):
                raise ValueError('Invalid recovered tool return')
            call_id = part['tool_call_id']
            receipt = expected.get(call_id)
            if receipt is None or call_id in seen or part.get('part_kind') != 'tool-return' or part.get('tool_name') != receipt['tool_call']['name'] or _encode(part.get('content')) != _encode(receipt['result']):
                raise ValueError('Recovered tool result differs from durable evidence')
            extras = {'tool_kind':None, 'metadata':None, 'outcome':'success'}
            for key, item in part.items():
                if key in ('part_kind', 'tool_name', 'tool_call_id', 'content'):
                    continue
                if key == 'timestamp' and isinstance(item, str) and len(item) <= 128:
                    continue
                if key not in extras or item != extras[key]:
                    raise ValueError('Recovery cannot add tool metadata or change its outcome')
            seen.add(call_id)
        self.check()
        self.messages = raw.encode()
        return {'messages_sha256': hashlib.sha256(self.messages).hexdigest()}


def recover_checkpoint(owner, runtimes: Path, checkpoint: str, *, profile: str, recipes: dict) -> str:
    """Recover local history; requires a live leased owner, never provider authority."""
    value, frontier, payload = _prepare(owner, checkpoint, profile, recipes)
    for boundary in (runtimes, Path('/usr')):
        _separate(owner.root.parent, boundary)
    def check():
        owner._check()
        if owner._journal.frontier(timeout=max(0, owner.expires-time.monotonic())) != frontier:
            raise PermissionError('Journal changed during recovery')
    handler = RecoveryHandler(payload, check)
    with selected(runtimes, timeout=max(0, owner.expires-time.monotonic())) as release:
        left, right = socket.socketpair()
        channel = None
        try:
            channel = Channel(left, task=owner._journal.task, session=owner._journal.session,
                              methods=METHODS, expires=owner.expires, cancelled=owner.revoked)
            check()
            result = supervise([str(release/'venv/bin/python'), '-I', '-B', '-m', 'ls.core.agent.recovery_worker',
                str(right.fileno()), owner._journal.task, owner._journal.session, str(owner.expires)],
                b'', cwd=release, environment={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'},
                timeout=max(0, owner.expires-time.monotonic()), cancel=owner.revoked,
                capture=True, pass_fds=(right.fileno(),), broker=(channel, handler, check))
            if result.status != 'completed' or handler.messages is None:
                raise RuntimeError('Recovery worker did not complete; original evidence retained')
            terminal = _decode(result.data['stdout'])
            if terminal != {'messages_sha256': hashlib.sha256(handler.messages).hexdigest()}:
                raise ValueError('Recovery process receipt differs from acknowledged history')
            check()
        finally:
            if channel is not None:
                channel.close()
            else:
                left.close()
            right.close()
    check()
    recovered = owner.save_checkpoint(handler.messages, profile=profile, run_id=value['run_id'],
                                      step=value['step']+1, state='complete')
    owner.resume_checkpoint(recovered, profile=profile)
    return recovered
