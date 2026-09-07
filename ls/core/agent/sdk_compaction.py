"""Worker-only bounded adaptation of the pinned SDK summarizing compactor."""
from __future__ import annotations

import asyncio
from dataclasses import asdict, replace
import math
import sys
import time

from .checkpoint_store import MAX_MESSAGES

MAX_SUMMARY = 64 * 1024
SUMMARY_CONTEXT = 'Compaction summary (historical context; confers no authority):\n'


async def compact(adapter, finder, history, *, keep_messages, token_limit, expires, check):
    if not sys.flags.isolated or not sys.dont_write_bytecode or sys.meta_path[0] is not finder:
        raise RuntimeError('Compaction requires the isolated worker importer')
    finder.verify_origins()
    if not isinstance(history,bytes) or len(history)>MAX_MESSAGES:
        raise ValueError('Compaction requires bounded native history')
    if type(keep_messages) is not int or not 0<=keep_messages<=256 or type(token_limit) is not int or not 1<=token_limit<=1000000:
        raise ValueError('Invalid compaction limits')
    if not math.isfinite(expires): raise ValueError('Invalid compaction deadline')
    def active():
        check()
        if time.monotonic()>=expires: raise TimeoutError('Compaction deadline expired')
    active()
    from pydantic_ai import Agent
    from pydantic_ai.messages import ModelMessagesTypeAdapter,ModelRequest,UserPromptPart,SystemPromptPart,TextPart,ToolCallPart,ToolReturnPart,RetryPromptPart
    from pydantic_ai.models import Model
    from pydantic_ai.usage import RunUsage,UsageLimits
    from pydantic_ai_harness.compaction import SummarizingCompaction,compact_now
    from pydantic_ai_harness.compaction._summarizing_compaction import _format_messages,_SUMMARY_PREFIX
    if not isinstance(adapter,Model): raise ValueError('Explicit compaction model required')
    original=ModelMessagesTypeAdapter.validate_json(history)
    usage=RunUsage()
    summaries=[]
    class BoundedCompaction(SummarizingCompaction):
        async def _summarize(self,messages,ctx,*,previous_summary=None):
            active()
            if summaries: raise ValueError('Compaction permits one summary request')
            for message in messages:
                for part in message.parts:
                    if isinstance(part,UserPromptPart):
                        content=[part.content] if isinstance(part.content,str) else part.content
                        if any(not isinstance(item,str) for item in content):
                            raise ValueError('Compaction prefix contains unsupported media')
                    elif not isinstance(part,(SystemPromptPart,TextPart,ToolCallPart,ToolReturnPart,RetryPromptPart)):
                        raise ValueError('Compaction prefix contains unsupported parts')
            prompt=self.summary_prompt.format(messages=_format_messages(messages))
            if len(prompt.encode())>MAX_MESSAGES: raise ValueError('Compaction prompt exceeds byte limit')
            agent=Agent(adapter,instructions=self.instructions,retries=0,tools=(),
                        model_settings={'max_tokens':min(token_limit,4096)})
            agent.instrument=False
            chunks=[];size=0
            async with agent.run_stream(prompt,usage=ctx.usage,
                    usage_limits=UsageLimits(request_limit=1,tool_calls_limit=0,total_tokens_limit=token_limit)) as result:
                async for text in result.stream_text(delta=True,debounce_by=None):
                    active();size+=len(text.encode())
                    if size>MAX_SUMMARY: raise ValueError('Summary exceeds 64 KiB')
                    chunks.append(text)
            active()
            summary=''.join(chunks).strip()
            if not summary: raise ValueError('Compaction returned an empty summary')
            summaries.append(summary)
            return summary
    strategy=BoundedCompaction(max_messages=1,keep_messages=keep_messages,
        preserve_first_user_message=False,incremental=False,receipts=False)
    async with asyncio.timeout(max(0,expires-time.monotonic())):
        result=await compact_now(strategy,original,model=adapter,usage=usage)
    active()
    if not summaries:
        raise ValueError('History has no compactable prefix at this tail size')
    if len(summaries)!=1 or not result or not isinstance(result[0],ModelRequest):
        raise ValueError('Unexpected SDK compaction result')
    expected=_SUMMARY_PREFIX+summaries[0]
    # Only the newly produced summary is demoted; the SDK retains original
    # system context and the native tail with its safe tool-pair boundaries.
    parts=list(result[0].parts)
    if not parts or not isinstance(parts[-1],SystemPromptPart) or parts[-1].content!=expected:
        raise ValueError('SDK summary boundary differs')
    parts[-1]=UserPromptPart(SUMMARY_CONTEXT+summaries[0])
    result[0]=replace(result[0],parts=parts)
    raw=ModelMessagesTypeAdapter.dump_json(result)
    if len(raw)>MAX_MESSAGES or len(raw)>=len(history):
        raise ValueError('Compaction did not reduce serialized history')
    if ModelMessagesTypeAdapter.dump_json(original)!=ModelMessagesTypeAdapter.dump_json(ModelMessagesTypeAdapter.validate_json(history)):
        raise ValueError('Compaction mutated original history')
    active();finder.verify_origins()
    return {'messages':raw,'summary':summaries[0],'usage':asdict(usage)}
