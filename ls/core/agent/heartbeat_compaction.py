"""Bounded compaction process receipts and owner-verified continuation evidence."""
import os

from .broker_rpc import _decode
from .compaction_content import usage
from .heartbeat_budget import _identity, _integer, _keys, DIGEST
from .registration_owner import _read
from .session_owner import _private
from .runtime_lock import LOCK_NAME

LIMIT = 16384


def validate(value, *, source, profile, token_limit):
    _identity(source, DIGEST)
    _identity(profile, DIGEST)
    _integer(token_limit, 1, 1000000)
    _keys(value, {'schema_version', 'source_checkpoint', 'checkpoint', 'profile', 'usage'})
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ValueError('Unsupported compaction receipt schema')
    for key in ('source_checkpoint', 'checkpoint', 'profile'):
        _identity(value[key], DIGEST)
    if value['source_checkpoint'] != source or value['profile'] != profile or value['checkpoint'] == source:
        raise ValueError('Compaction receipt differs from the authorized source/profile')
    usage(value['usage'], token_limit)
    return value


class Receipt:
    """Adapter for the existing bounded heartbeat process pump, without raw tails."""
    def __init__(self, *, source, profile, token_limit):
        _identity(source, DIGEST)
        _identity(profile, DIGEST)
        if type(token_limit) is not int or not 1 <= token_limit <= 1000000:
            raise ValueError('Invalid compaction token limit')
        self.source, self.profile, self.token_limit = source, profile, token_limit
        self.buffer = bytearray()
        self.finished = False

    def feed(self, raw):
        if self.finished or len(self.buffer)+len(raw) > LIMIT:
            raise ValueError('Compaction receipt is closed or exceeds bounds')
        self.buffer.extend(raw)
        # Compaction has no streaming progress contract; partial JSON is not progress.
        return False

    def finish(self, returncode):
        if self.finished:
            raise ValueError('Compaction receipt is already finished')
        self.finished = True
        try:
            value = validate(_decode(self.buffer), source=self.source,
                             profile=self.profile, token_limit=self.token_limit)
        except (ValueError, TypeError, RecursionError) as exc:
            raise ValueError('Invalid compaction process receipt') from exc
        return {'completed': returncode == 0, 'receipt': value}


def verify(owner, value, *, source, profile, token_limit):
    """Caller holds the exact task/session lease; receipt text never creates authority."""
    owner._check()
    validate(value, source=source, profile=profile, token_limit=token_limit)
    # Older owner readers create locks. Refuse incomplete storage before calling them.
    for child in ('checkpoints', 'journal'):
        fd = _private(owner.root/child)
        try:
            if _read(fd, LOCK_NAME) is None:
                raise FileNotFoundError('Compaction coordination evidence is missing')
        finally:
            os.close(fd)
    fd = _private(owner.root)
    try:
        raw = _read(fd, 'compaction-'+value['checkpoint']+'.json')
    finally:
        os.close(fd)
    if raw is None or len(raw) > LIMIT:
        raise ValueError('Compaction process receipt lacks matching owner evidence')
    recorded = validate(_decode(raw), source=source, profile=profile, token_limit=token_limit)
    if recorded != value:
        raise ValueError('Compaction process receipt differs from owner evidence')
    owner.resume_checkpoint(source, profile=profile)
    owner.resume_checkpoint(value['checkpoint'], profile=profile)
    owner._check()
    return value['checkpoint']
