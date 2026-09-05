"""Deterministic isolated SDK iteration fixture; no provider requests."""
import asyncio
import json
from pathlib import Path
import sys
import time

if len(sys.argv) == 2:
    sys.path.insert(0, sys.argv[1])
    payload = Path(sys.argv[1])/'vendor/lscli'
else:
    import ls
    payload = Path(ls.__file__).parent/'_sdk_payload'
from ls.core.agent.sdk_imports import activate
finder = activate(payload)
from ls.core.agent.sdk_iteration import iterate
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import Tool
from pydantic_ai.messages import ModelMessagesTypeAdapter
from pydantic_ai_harness.step_persistence import InMemoryStepStore


async def main():
    calls, events = [], []
    async def fixture(value: str) -> str:
        calls.append(value)
        return 'broker fixture result'
    tool = Tool(fixture, sequential=True, max_retries=0)
    store = InMemoryStepStore()
    async def emit(raw): events.append(json.loads(raw))
    def check(): pass
    common = dict(finder=finder, prompt='Use fixture then answer', instructions='Use only granted tools.',
                  tools=(tool,), store=store, on_event=emit, check=check, expires=time.monotonic()+10,
                  run_id='fixture-run', conversation_id='fixture-conversation')
    result = await iterate(TestModel(custom_output_text='finished'), **common)
    assert result['output'] == 'finished' and len(calls) == 1 and events
    snapshot = await store.latest_snapshot(run_id='fixture-run')
    assert snapshot is not None and snapshot.state == 'complete'
    assert ModelMessagesTypeAdapter.dump_json(snapshot.messages) == result['messages']
    assert not await store.list_unresolved_tool_effects(run_id='fixture-run')
    resumed = await iterate(TestModel(call_tools=[], custom_output_text='continued'), **(common | dict(
        tools=(), run_id='resumed-run', history=result['messages'])))
    assert resumed['output'] == 'continued' and len(calls) == 1
    try: await iterate(TestModel(), **(common | dict(run_id='limited', tool_limit=0)))
    except Exception as exc: assert type(exc).__name__ == 'UsageLimitExceeded', type(exc).__name__
    else: raise AssertionError('tool bound not enforced')
    assert len(calls) == 1
    def denied(): raise PermissionError('revoked fixture')
    try: await iterate(TestModel(), **(common | dict(run_id='denied', check=denied)))
    except PermissionError: pass
    else: raise AssertionError('authority check ignored')
    import ls.core.agent.sdk_iteration as implementation
    previous_limit = implementation.MAX_EVENTS
    implementation.MAX_EVENTS = 1
    try:
        try: await iterate(TestModel(call_tools=[]), **(common | dict(tools=(), run_id='overflow')))
        except ValueError as exc: assert 'stream exceeds' in str(exc)
        else: raise AssertionError('stream byte bound ignored')
    finally:
        implementation.MAX_EVENTS = previous_limit
    async def slow_emit(raw): await asyncio.sleep(10)
    try:
        await iterate(TestModel(call_tools=[]), **(common | dict(tools=(), run_id='timeout',
            expires=time.monotonic()+.05, on_event=slow_emit)))
    except TimeoutError: pass
    else: raise AssertionError('callback deadline ignored')
    async def cancel_emit(raw): raise asyncio.CancelledError()
    try:
        await iterate(TestModel(call_tools=[]), **(common | dict(tools=(), run_id='cancelled', on_event=cancel_emit)))
    except asyncio.CancelledError: pass
    else: raise AssertionError('cancellation swallowed')
    from pydantic_ai.run import AgentRunResult
    from types import SimpleNamespace
    original_dump, original_clock = AgentRunResult.all_messages_json, implementation.time
    def late_dump(self, *args, **kwargs):
        result = original_dump(self, *args, **kwargs)
        implementation.time = SimpleNamespace(monotonic=lambda: common['expires']+1)
        return result
    AgentRunResult.all_messages_json = late_dump
    try:
        try: await iterate(TestModel(call_tools=[]), **(common | dict(tools=(), run_id='late-serialization')))
        except TimeoutError: pass
        else: raise AssertionError('post-serialization deadline ignored')
    finally:
        AgentRunResult.all_messages_json = original_dump
        implementation.time = original_clock
    print(json.dumps({'stream_events':len(events), 'tool_calls':len(calls), 'snapshot_state':snapshot.state,
                      'resumed':resumed['output'], 'origins':finder.verify_origins()}))
asyncio.run(main())
