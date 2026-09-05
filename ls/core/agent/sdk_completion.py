"""Isolated, one-attempt direct SDK model completion without an agent or tools."""
import asyncio
import sys
import math
import time
from .broker_rpc import _encode
from .completion_contract import parse,validate_output,envelope
from .completion_response import Capture,Rejected
from .sdk_models import model


async def complete(profile,environment,finder,raw,*,expires,check,transport=None):
    if not sys.flags.isolated or not sys.dont_write_bytecode or sys.meta_path[0] is not finder:
        raise RuntimeError('Completion requires isolated SDK importer')
    started=time.monotonic()
    finder.verify_origins()
    if not math.isfinite(expires):raise ValueError('Invalid completion deadline')
    request=parse(raw,profile)
    expires=min(expires,started+request.deadline_seconds)
    settings={'max_tokens':request.max_output_tokens}
    if request.reasoning_effort is not None:
        settings['openai_reasoning_effort']=request.reasoning_effort
    attempts=0;usage=None
    def active():
        check()
        if time.monotonic()>=expires:raise TimeoutError('Completion deadline')
    capture=Capture(profile.api,active)
    try:
        active()
        try:profile.credential(environment)
        except ValueError:return envelope('unavailable',model=profile.model)
        from pydantic_ai.messages import ModelRequest,UserPromptPart
        from pydantic_ai.models import ModelRequestParameters
        from pydantic_ai.output import OutputObjectDefinition
        parameters=ModelRequestParameters()
        if request.schema_mode=='native':
            parameters.output_mode='native'
            parameters.output_object=OutputObjectDefinition(request.output_schema,name='completion',strict=True)
        prompt=_encode(request.input).decode()
        async with asyncio.timeout(min(request.deadline_seconds,max(0,expires-time.monotonic()))):
            async with model(profile,environment,finder,transport=transport,response_guard=capture) as adapter:
                active();attempts=1
                result=await adapter.request([ModelRequest(parts=[UserPromptPart(prompt)])],
                    settings,parameters)
        active();finder.verify_origins()
        usage={'input_tokens':result.usage.input_tokens,'output_tokens':result.usage.output_tokens}
        status,data=validate_output(capture.text,request)
        answer=envelope(status,model=profile.model,data=data,usage=usage,request_id=capture.request_id,attempts=attempts)
        active()
        return answer
    except Rejected as error:status=error.status
    except TimeoutError:status='deadline'
    except PermissionError:status='cancelled'
    except Exception as error:
        import httpx2 as httpx
        from openai import APIConnectionError
        chain=[];cause=error
        while cause is not None and len(chain)<8 and all(cause is not previous for previous in chain):
            chain.append(cause);cause=cause.__cause__
        status='transport_failed' if any(isinstance(e,(httpx.ConnectError,httpx.ConnectTimeout)) for e in chain) else 'uncertain' if any(isinstance(e,(APIConnectionError,httpx.TransportError)) for e in chain) else 'provider_error'

    status=capture.status or status
    return envelope(status,model=profile.model,usage=usage,request_id=capture.request_id,attempts=attempts)
