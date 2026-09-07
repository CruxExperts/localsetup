"""Supervise provider-free portable history conversion in the sealed SDK runtime."""
from __future__ import annotations

import hashlib
import socket
import time

from .broker_rpc import Channel, _encode, _decode
from .checkpoint_store import MAX_MESSAGES
from .runtime_install import selected
from .supervisor import supervise

METHODS = frozenset({'portable.start', 'portable.finish'})


class Handler:
    def __init__(self, history, images, check):
        self.payload = {'history': history.decode(), 'images': images}
        self.digest = hashlib.sha256(_encode(self.payload)).hexdigest()
        self.check, self.started, self.messages = check, False, None

    def __call__(self, method, data):
        self.check()
        if self.messages is not None: raise ValueError('Portable exchange already finished')
        if method == 'portable.start' and data == {} and not self.started:
            self.started = True
            return {'input_sha256': self.digest, 'payload': self.payload}
        if method != 'portable.finish' or not self.started or not isinstance(data, dict) or set(data) != {'input_sha256', 'messages'} or data['input_sha256'] != self.digest:
            raise ValueError('Invalid portable exchange')
        raw = data['messages']
        if not isinstance(raw, str) or len(raw.encode()) > MAX_MESSAGES:
            raise ValueError('Portable history exceeds limit')
        from .portable_content import accept
        accept(raw, self.payload['history'], images=self.payload['images'])
        self.check()
        self.messages = raw.encode()
        return {'messages_sha256': hashlib.sha256(self.messages).hexdigest()}


def convert(owner, runtimes, history, *, images):
    handler = Handler(history, images, owner._check)
    from .session_owner import _separate
    _separate(owner.root.parent, runtimes)
    with selected(runtimes, timeout=max(0, owner.expires-time.monotonic())) as release:
        left, right = socket.socketpair()
        channel = None
        try:
            channel = Channel(left, task=owner._journal.task, session=owner._journal.session,
                              methods=METHODS, expires=owner.expires, cancelled=owner.revoked)
            outcome = supervise([str(release/'venv/bin/python'), '-I', '-B', '-m',
                'ls.core.agent.portable_worker', str(right.fileno()), owner._journal.task,
                owner._journal.session, str(owner.expires)], b'', cwd=release,
                environment={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'},
                timeout=max(0,owner.expires-time.monotonic()), cancel=owner.revoked,
                capture=True, pass_fds=(right.fileno(),), broker=(channel,handler,owner._check))
            if outcome.status != 'completed' or handler.messages is None:
                raise RuntimeError('Portable worker did not complete')
            if _decode(outcome.data['stdout']) != {'messages_sha256':hashlib.sha256(handler.messages).hexdigest()}:
                raise ValueError('Portable process receipt differs')
            owner._check()
            return handler.messages
        finally:
            if channel is not None: channel.close()
            else: left.close()
            right.close()
