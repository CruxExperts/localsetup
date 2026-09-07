"""Worker-only bounded SDK iteration; supervisor owns grants and persistence."""
from __future__ import annotations

import asyncio
from dataclasses import asdict
import math
import sys
import time

MAX_HISTORY = 8 * 1024 * 1024
MAX_EVENTS = 1024 * 1024


async def iterate(adapter, finder, *, prompt, instructions, tools, store, on_event, check,
                  expires, run_id, conversation_id, history=None, request_limit=8,
                  tool_limit=16, token_limit=32768, steering=None, images=()):
    """Use SDK node streaming and StepPersistence with explicit caller boundaries.

    `check` is synchronous current supervisor authority, not saved conversation
    policy. `store` must acknowledge persistence before returning. Callers must
    reconcile effects before supplying any restored message history.
    """
    if not sys.flags.isolated or not sys.dont_write_bytecode or sys.meta_path[0] is not finder:
        raise RuntimeError('SDK iteration requires the active isolated worker importer')
    finder.verify_origins()
    from pydantic import TypeAdapter
    from pydantic_ai import Agent
    from pydantic_ai.messages import ModelMessagesTypeAdapter, UserPromptPart, BinaryContent
    from pydantic_ai.models import Model
    from pydantic_ai.models.openai import OpenAIResponsesModel
    from pydantic_ai.tools import Tool
    from pydantic_ai.usage import UsageLimits
    from pydantic_ai_harness.step_persistence import StepPersistence
    if not isinstance(adapter, Model) or not isinstance(tools, tuple):
        raise ValueError('Iteration requires an explicit model and immutable tool inventory')
    if any(not isinstance(tool, Tool) or not tool.sequential or tool.max_retries != 0 for tool in tools):
        raise ValueError('Broker tools must be sequential with zero retries')
    if len({tool.name for tool in tools}) != len(tools):
        raise ValueError('Broker tool names must be unique')
    if any(type(value) is not int or value < 1 for value in (request_limit, token_limit)) or type(tool_limit) is not int or tool_limit < 0:
        raise ValueError('Iteration usage limits must be finite positive counts (tools may be zero)')
    if not math.isfinite(expires) or expires <= time.monotonic():
        raise TimeoutError('Iteration deadline expired')
    if any(not isinstance(value, str) or not value or len(value.encode()) > MAX_HISTORY for value in (prompt, instructions, run_id, conversation_id)):
        raise ValueError('Iteration requires bounded explicit prompt, instructions and identities')
    if history is not None and (not isinstance(history, bytes) or len(history) > MAX_HISTORY):
        raise ValueError('SDK history exceeds its byte limit')
    if not isinstance(images,tuple) or len(images)>4 or any(not isinstance(image,BinaryContent) for image in images):
        raise ValueError('SDK images require bounded native binary content')
    def active():
        check()
        if time.monotonic() >= expires:
            raise TimeoutError('Iteration deadline expired')
    active()
    messages = None if history is None else ModelMessagesTypeAdapter.validate_json(history)
    agent = Agent(adapter, tools=tools, instructions=instructions, retries=0,
                  capabilities=[StepPersistence(store=store)])
    agent.instrument = False
    limits = UsageLimits(request_limit=request_limit, tool_calls_limit=tool_limit, total_tokens_limit=token_limit)
    emitted = 0
    try:
        async with asyncio.timeout(max(0, expires-time.monotonic())):
            async with agent.iter([prompt,*images] if images else prompt, message_history=messages, run_id=run_id,
                                  conversation_id=conversation_id, usage_limits=limits) as run:
                async for node in run:
                    active()
                    if Agent.is_call_tools_node(node) and isinstance(adapter, OpenAIResponsesModel):
                        response = node.model_response
                        if (response.state != 'complete' or response.finish_reason != 'stop'
                                or (response.provider_details or {}).get('finish_reason') != 'completed'
                                or (response.provider_details or {}).get('background')):
                            raise ValueError('Responses coding requires a completed foreground response before dispatch')
                    if Agent.is_model_request_node(node) and steering is not None:
                        additions = await steering()
                        active()
                        if (not isinstance(additions,list) or len(additions)>32
                                or any(not isinstance(x,str) or not x or len(x.encode())>8192 for x in additions)):
                            raise ValueError('Invalid steering messages')
                        node.request.parts.extend(UserPromptPart(text) for text in additions)
                    if Agent.is_model_request_node(node) or Agent.is_call_tools_node(node):
                        async with node.stream(run.ctx) as stream:
                            async for event in stream:
                                active()
                                raw = TypeAdapter(type(event)).dump_json(event)
                                emitted += len(raw)
                                if emitted > MAX_EVENTS:
                                    raise ValueError('SDK stream exceeds its byte limit')
                                await on_event(raw)
                if run.result is None:
                    raise RuntimeError('SDK iteration ended without a result')
                result = run.result
            active()
            serialized = result.all_messages_json()
            if len(serialized) > MAX_HISTORY or not isinstance(result.output, str) or len(result.output.encode()) > MAX_EVENTS:
                raise ValueError('SDK result exceeds its output/history limit')
            active()
            return {'output': result.output, 'messages': serialized, 'usage': asdict(result.usage)}
    finally:
        finder.verify_origins()
