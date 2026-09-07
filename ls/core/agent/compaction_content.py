"""Supervisor checks on compacted history; summaries never become authority."""
from datetime import datetime

from .broker_rpc import _decode, _encode
from .checkpoint_store import MAX_MESSAGES
from .sdk_compaction import MAX_SUMMARY, SUMMARY_CONTEXT


def accept(history, raw, summary, *, keep_messages):
    if not isinstance(summary,str) or not summary.strip() or len(summary.encode())>MAX_SUMMARY:
        raise ValueError('Invalid compaction summary')
    if not isinstance(raw,str) or len(raw.encode())>MAX_MESSAGES or len(raw.encode())>=len(history.encode()):
        raise ValueError('Compaction must reduce bounded history')
    original,result=_decode(history),_decode(raw)
    if not isinstance(original,list) or not isinstance(result,list) or not result or not isinstance(result[0],dict):
        raise ValueError('Invalid compacted message array')
    tail=result[1:];cutoff=len(original)-len(tail)
    if cutoff<=0 or len(tail)<min(keep_messages,len(original)) or _encode(tail)!=_encode(original[cutoff:]):
        raise ValueError('Compaction changed required native tail')
    # A tool call/result pair cannot cross the selected boundary.
    calls={p.get('tool_call_id') for m in original[:cutoff] for p in m.get('parts',[]) if p.get('part_kind')=='tool-call'}
    if any(p.get('part_kind') in ('tool-return','retry-prompt') and p.get('tool_call_id') in calls for m in tail for p in m.get('parts',[])):
        raise ValueError('Compaction split a tool pair')
    systems=[]
    stopped=False
    for message in original:
        if message.get('kind')!='request':break
        for part in message.get('parts',[]):
            if part.get('part_kind')=='system-prompt' and not part.get('content','').startswith('Summary of previous conversation:\n\n'):
                systems.append(part)
            else:stopped=True;break
        if stopped:break
    first=result[0]
    defaults={'kind':'request','timestamp':None,'instructions':None,'run_id':None,'conversation_id':None,'metadata':None,'state':'complete'}
    if first.get('kind')!='request' or any(k!='parts' and (k not in defaults or v!=defaults[k]) for k,v in first.items()):
        raise ValueError('Compaction cannot add request instructions or metadata')
    parts=first.get('parts')
    if not isinstance(parts,list) or len(parts)!=len(systems)+1 or _encode(parts[:-1])!=_encode(systems):
        raise ValueError('Compaction changed original system context')
    part=parts[-1]
    if not isinstance(part,dict) or set(part)!={'part_kind','content','timestamp'} or part['part_kind']!='user-prompt' or part['content']!=SUMMARY_CONTEXT+summary:
        raise ValueError('Summary must be inert user context')
    if not isinstance(part['timestamp'],str) or len(part['timestamp'])>64:raise ValueError('Invalid summary timestamp')
    datetime.fromisoformat(part['timestamp'])


def usage(value, token_limit):
    fields={'requests','tool_calls','input_tokens','output_tokens'}
    if not isinstance(value,dict) or set(value)!=fields or any(type(x) is not int or x<0 for x in value.values()):
        raise ValueError('Invalid compaction usage')
    if value['requests']!=1 or value['tool_calls']!=0 or value['input_tokens']+value['output_tokens']>token_limit:
        raise ValueError('Compaction usage exceeds request/tool/token budget')
