"""Pinned Responses stream adaptation: terminal evidence precedes tool dispatch."""
from contextlib import asynccontextmanager


class CompletedEvents:
    """Wrap the pinned SDK's peekable event source without buffering its body."""
    def __init__(self,events):
        self.events=events
        self.source=events.source

    async def __aiter__(self):
        last=-1;created=False;completed=False
        async for event in self.events:
            sequence=getattr(event,'sequence_number',None)
            kind=getattr(event,'type',None)
            if completed or type(sequence) is not int or sequence<=last:
                raise ValueError('Responses stream has contradictory terminal or sequence evidence')
            last=sequence
            if not created:
                if kind!='response.created':raise ValueError('Responses stream lacks creation evidence')
                created=True
            elif kind=='response.created':raise ValueError('Responses stream repeated creation evidence')
            response=getattr(event,'response',None)
            if response is not None and getattr(response,'background',False):
                raise ValueError('Background Responses workflows are not qualified')
            if kind in ('response.failed','response.incomplete','error'):
                raise ValueError('Responses stream did not complete successfully')
            if kind=='response.completed':
                if (getattr(response,'status',None)!='completed' or getattr(response,'error',None) is not None
                        or getattr(response,'incomplete_details',None) is not None):
                    raise ValueError('Responses terminal status is inconsistent')
                completed=True
            yield event
        if not completed:raise ValueError('Responses stream lacks completed terminal evidence')


def guarded_type(base):
    class ForegroundResponses(base):
        @asynccontextmanager
        async def request_stream(self,messages,model_settings,model_request_parameters,run_context=None):
            async with super().request_stream(messages,model_settings,model_request_parameters,run_context) as response:
                # Pinned SDK contract: OpenAIResponsesStreamedResponse consumes
                # _response, and close_stream closes _response.source.
                events=getattr(response,'_response',None)
                if events is None or not hasattr(events,'source'):
                    raise ValueError('Unsupported Responses stream implementation')
                response._response=CompletedEvents(events)
                yield response
    return ForegroundResponses
