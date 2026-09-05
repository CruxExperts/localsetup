"""Bound raw completion evidence before SDK normalization and return no diagnostics."""
import re
import httpx2 as httpx
from .broker_rpc import _decode
from .completion_contract import MAX_OUTPUT


class Rejected(ValueError):
    def __init__(self,status):self.status=status;super().__init__(status)


class Capture:
    def __init__(self,api,check):
        self.api=api;self.check=check;self.request_id=None;self.status=None;self.text=None

    async def __call__(self,response):
        try: return await self.read(response)
        except PermissionError:
            self.status='cancelled';raise
        except TimeoutError:
            self.status='deadline';raise
        except Rejected as error:
            self.status=error.status
            raise

    async def read(self,response):
        raw=bytearray()
        try:
            if response.headers.get('content-encoding','identity').lower() != 'identity':
                raise Rejected('provider_error')
            async for chunk in response.aiter_bytes():
                self.check()
                if len(raw)+len(chunk)>MAX_OUTPUT+65536:raise Rejected('output_limit')
                raw.extend(chunk)
        finally:await response.aclose()
        self.check()
        identifier=response.headers.get('x-request-id')
        if identifier and re.fullmatch(r'[A-Za-z0-9_.:-]{1,256}',identifier):self.request_id=identifier
        if response.status_code>=400:
            self.status='rate_limited' if response.status_code==429 else 'unavailable' if response.status_code in (401,403) else 'provider_error'
            raise Rejected(self.status)
        try:
            value=_decode(bytes(raw));self.text=extract(value,self.api)
        except Rejected:raise
        except (ValueError,TypeError,KeyError,IndexError,AttributeError,RecursionError):raise Rejected('malformed') from None
        headers={key:value for key,value in response.headers.items() if key.lower() not in ('content-encoding','content-length','transfer-encoding')}
        return httpx.Response(response.status_code,headers=headers,content=bytes(raw))


def extract(value,api):
    if api=='chat_completions':
        choices=value['choices']
        if len(choices)!=1:raise Rejected('malformed')
        choice=choices[0];message=choice['message']
        if message.get('refusal') or choice.get('finish_reason')=='content_filter':raise Rejected('refused')
        if choice.get('finish_reason')!='stop':raise Rejected('incomplete')
        if message.get('tool_calls') or message.get('function_call'):raise Rejected('malformed')
        text=message['content']
    else:
        if value.get('background'):raise Rejected('incomplete')
        output=value['output']
        if any(part.get('type')=='refusal' for item in output if item.get('type')=='message' for part in item.get('content',[])):
            raise Rejected('refused')
        if value.get('status')!='completed' or value.get('error') or value.get('incomplete_details'):
            raise Rejected('incomplete')
        chunks=[]
        for item in output:
            if item['type']=='reasoning':continue
            if item['type']!='message':raise Rejected('malformed')
            for part in item['content']:
                if part['type']!='output_text' or not isinstance(part.get('text'),str):raise Rejected('malformed')
                chunks.append(part['text'])
        text=''.join(chunks)
    if not isinstance(text,str):raise Rejected('malformed')
    return text
