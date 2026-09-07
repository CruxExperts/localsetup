"""Native pre-tool history acknowledgement shared by isolated broker tools."""
from __future__ import annotations
import sys
from .checkpoint_store import MAX_MESSAGES
from .operation_journal import DIGEST


async def pretool_checkpoint(finder, channel, ctx):
    if not sys.flags.isolated or not sys.dont_write_bytecode or sys.meta_path[0] is not finder:
        raise RuntimeError('SDK tool checkpoints require the active isolated worker importer')
    from pydantic_ai.messages import ModelMessagesTypeAdapter
    history=ModelMessagesTypeAdapter.dump_json(ctx.messages)
    if len(history)>MAX_MESSAGES:
        raise ValueError('Pre-tool checkpoint exceeds history limit')
    checkpoint=await channel.request_async('checkpoint.save',{'messages':history.decode(),
                                                            'step':ctx.run_step,'state':'interrupted'})
    if not isinstance(checkpoint,dict) or set(checkpoint)!={'digest'} or not isinstance(checkpoint['digest'],str) or not DIGEST.fullmatch(checkpoint['digest']):
        channel.close()
        raise ValueError('Invalid pre-tool checkpoint acknowledgement')
    finder.verify_origins()
    return checkpoint['digest']
