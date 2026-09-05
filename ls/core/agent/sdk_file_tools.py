"""Isolated SDK file tools delegate authority and effects to the supervisor."""
from __future__ import annotations

import sys

from .checkpoint_store import MAX_MESSAGES
from .operation_journal import DIGEST


def file_tools(finder, channel):
    if not sys.flags.isolated or not sys.dont_write_bytecode or sys.meta_path[0] is not finder:
        raise RuntimeError('SDK file tools require the active isolated worker importer')
    finder.verify_origins()
    from pydantic_ai.messages import ModelMessagesTypeAdapter
    from pydantic_ai.tools import Tool

    async def read_file(path: str) -> dict:
        """Read granted UTF-8 text and its SHA-256 digest."""
        return await channel.request_async('file.read', {'path':path})

    async def write_file(ctx, path: str, content: str, expected_before: str | None) -> dict:
        """Replace granted UTF-8 text only when its digest matches; null requires absence."""
        history = ModelMessagesTypeAdapter.dump_json(ctx.messages)
        if len(history) > MAX_MESSAGES:
            raise ValueError('Pre-tool checkpoint exceeds history limit')
        checkpoint = await channel.request_async('checkpoint.save', {'messages':history.decode(),
                                                                    'step':ctx.run_step,'state':'interrupted'})
        if not isinstance(checkpoint, dict) or set(checkpoint) != {'digest'} or not isinstance(checkpoint['digest'], str) or not DIGEST.fullmatch(checkpoint['digest']):
            channel.close()
            raise ValueError('Invalid pre-tool checkpoint acknowledgement')
        return await channel.request_async('file.write', {'path':path,'content':content,
            'expected_before':expected_before,'checkpoint':checkpoint['digest'],'call_id':ctx.tool_call_id})

    # Explicit takes_ctx avoids resolving a local-scope annotation through globals.
    tools = (Tool(read_file, sequential=True, max_retries=0),
             Tool(write_file, takes_ctx=True, sequential=True, max_retries=0))
    finder.verify_origins()
    return tools
