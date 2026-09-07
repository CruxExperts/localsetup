import json,subprocess,sys
from pathlib import Path


def test_responses_streamed_tool_call_and_native_resume():
    root=Path(__file__).resolve().parents[2]
    result=subprocess.run([sys.executable,'-I','-B',str(root/'ls/tests/sdk_responses_fixture.py'),str(root)],capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
    report=json.loads(result.stdout)
    assert report['requests']==3 and report['tool_calls']==1 and report['native_resume'] and report['stream_events']>0


def test_raw_response_stream_rejects_background_and_invalid_sequence():
    import asyncio
    from types import SimpleNamespace as Event
    from ls.core.agent.sdk_response_stream import CompletedEvents
    class Events:
        source=object()
        def __init__(self,values):self.values=values
        async def __aiter__(self):
            for value in self.values:yield value
    async def collect(values):
        return [event async for event in CompletedEvents(Events(values))]
    created=Event(type='response.created',sequence_number=0,response=Event(background=False))
    completed=Event(type='response.completed',sequence_number=1,response=Event(background=False,status='completed',error=None,incomplete_details=None))
    assert len(asyncio.run(collect([created,completed])))==2
    cases=[[completed],[created,created],[created,completed,completed],
           [Event(type='response.created',sequence_number=0,response=Event(background=True))],
           [created,Event(type='response.completed',sequence_number=1,response=Event(background=False,status='failed',error=None,incomplete_details=None))]]
    for events in cases:
        try:asyncio.run(collect(events))
        except ValueError:pass
        else:raise AssertionError('Malformed stream accepted')
