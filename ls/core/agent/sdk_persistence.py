"""Worker snapshot acknowledgements over RPC; operation authority stays outside SDK."""
from __future__ import annotations

import asyncio
import sys

from .checkpoint_rpc import METHOD
from .checkpoint_store import MAX_MESSAGES
from .operation_journal import DIGEST, IDENTIFIER


def checkpoint_store(finder, channel, *, run_id: str):
    if not sys.flags.isolated or not sys.dont_write_bytecode or sys.meta_path[0] is not finder:
        raise RuntimeError('SDK persistence requires the active isolated worker importer')
    finder.verify_origins()
    if not isinstance(run_id, str) or not IDENTIFIER.fullmatch(run_id):
        raise ValueError('SDK persistence requires an explicit run identity')
    from pydantic_ai.messages import ModelMessagesTypeAdapter
    from pydantic_ai_harness.step_persistence import InMemoryStepStore
    finder.verify_origins()

    class AcknowledgedSnapshots(InMemoryStepStore):
        def __init__(self):
            super().__init__(max_snapshots_per_run=2)
            self.last_checkpoint = None
            self._save_lock = asyncio.Lock()

        async def register_run(self, record):
            if record.run_id != run_id:
                raise PermissionError('SDK persistence run identity mismatch')
            await super().register_run(record)

        async def save_snapshot(self, snapshot):
            async with self._save_lock:
                await self._save(snapshot)

        async def _save(self, snapshot):
            if snapshot.run_id != run_id:
                raise PermissionError('SDK checkpoint run identity mismatch')
            # Stage the pinned SDK's own acceptance/retention algorithm. These
            # two private fields are an explicit Harness compatibility boundary.
            class Pending(list):
                accepted = False
                def append(self, item):
                    self.accepted = True
                    super().append(item)
            pending = Pending(self._snapshots.get(run_id, ()))
            candidate = InMemoryStepStore(max_snapshots_per_run=2)
            candidate._snapshots[run_id] = pending
            candidate._snapshot_key_high_water = {
                key: (sequence, set(keys)) for key, (sequence, keys) in self._snapshot_key_high_water.items()}
            await candidate.save_snapshot(snapshot)
            if not pending.accepted:
                return
            raw = ModelMessagesTypeAdapter.dump_json(snapshot.messages)
            if len(raw) > MAX_MESSAGES:
                raise ValueError('SDK checkpoint history exceeds byte limit')
            result = await channel.request_async(METHOD, {'messages': raw.decode('utf-8'),
                                                         'step': snapshot.step_index, 'state': snapshot.state})
            if not isinstance(result, dict) or set(result) != {'digest'} or not isinstance(result['digest'], str) or not DIGEST.fullmatch(result['digest']):
                channel.close()
                raise ValueError('Invalid durable checkpoint acknowledgement')
            self._snapshots = candidate._snapshots
            self._snapshot_key_high_water = candidate._snapshot_key_high_water
            self.last_checkpoint = result['digest']
            finder.verify_origins()

    return AcknowledgedSnapshots()
