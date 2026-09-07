"""Supervisor-owned checkpoint method; worker payloads do not select authority."""
from __future__ import annotations

from .checkpoint_store import MAX_MESSAGES
from .operation_journal import DIGEST, IDENTIFIER

METHOD = 'checkpoint.save'


class CheckpointHandler:
    def __init__(self, owner, *, profile: str, run_id: str):
        if not isinstance(profile, str) or not DIGEST.fullmatch(profile) or not isinstance(run_id, str) or not IDENTIFIER.fullmatch(run_id):
            raise ValueError('Checkpoint handler requires explicit profile and run identity')
        self.owner, self.profile, self.run_id = owner, profile, run_id

    def __call__(self, method, data):
        if method != METHOD or not isinstance(data, dict) or set(data) != {'messages','step','state'}:
            raise ValueError('Unsupported checkpoint RPC method or schema')
        if not isinstance(data['messages'], str) or len(data['messages'].encode()) > MAX_MESSAGES:
            raise ValueError('Checkpoint RPC message history exceeds limit')
        digest = self.owner.save_checkpoint(data['messages'].encode(), profile=self.profile,
                                           run_id=self.run_id, step=data['step'], state=data['state'])
        return {'digest': digest}
