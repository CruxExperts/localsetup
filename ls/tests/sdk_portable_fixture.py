"""Native portable conversion and tool-free continuation fixture."""
import json
from pathlib import Path
import sys

if len(sys.argv)==2:
    sys.path.insert(0,sys.argv[1]);payload=Path(sys.argv[1])/'./vendor/lscli'
else:
    import ls
    payload=Path(ls.__file__).parent/'_sdk_payload'
from ls.core.agent.sdk_imports import activate
finder=activate(payload)
from ls.core.agent.sdk_portable import convert
from pydantic_ai.messages import (ModelMessagesTypeAdapter,ModelRequest,ModelResponse,
    UserPromptPart,SystemPromptPart,TextPart,ToolCallPart,ToolReturnPart,BinaryContent,ThinkingPart,ImageUrl)
image=b'\x89PNG\r\n\x1a\n'+b'\x00\x00\x00\rIHDR'+b'\x00'*8
messages=[ModelRequest(parts=[SystemPromptPart('Historical system text'),UserPromptPart(['Original task',BinaryContent(image,media_type='image/png')])]),
 ModelResponse(parts=[ToolCallPart('write_file',{'path':'a','content':'old'},'call')],provider_response_id='PRIVATE_PROVIDER_ID'),
 ModelRequest(parts=[ToolReturnPart('write_file',{'status':'applied'},'call')]),
 ModelResponse(parts=[TextPart('Saved answer')])]
history=ModelMessagesTypeAdapter.dump_json(messages)
converted=convert(finder,history,images=True)
from ls.core.agent.portable_content import accept
accept(converted,history,images=True)
changed=json.loads(converted);changed[0]['parts'][0]['content'][1]['data']='AA=='
try:accept(json.dumps(changed),history,images=True)
except ValueError:pass
else:raise AssertionError('Changed image accepted')
parsed=ModelMessagesTypeAdapter.validate_json(converted)
assert len(parsed)==1 and len(parsed[0].parts)==1 and isinstance(parsed[0].parts[0],UserPromptPart)
text,attachment=parsed[0].parts[0].content
assert attachment.data==image
assert all(word in text for word in ['Original task','Historical system text','Saved answer','write_file','applied'])
assert b'PRIVATE_PROVIDER_ID' not in converted
assert ModelMessagesTypeAdapter.dump_json(messages)==history
refusals=0
for value,images in [(history,False),(ModelMessagesTypeAdapter.dump_json([ModelResponse(parts=[ThinkingPart('private reasoning')])]),False),
 (ModelMessagesTypeAdapter.dump_json([ModelRequest(parts=[UserPromptPart([ImageUrl('https://example.test/image.png')])])]),True)]:
 try:convert(finder,value,images=images)
 except ValueError:refusals+=1
 else:raise AssertionError('Unsupported conversion accepted')
from pydantic_ai import Agent
from pydantic_ai.models.function import FunctionModel
calls=[]
def respond(messages,info):
 calls.append(messages)
 assert all(not isinstance(p,ToolCallPart) for m in messages for p in m.parts)
 return ModelResponse(parts=[TextPart('continued')])
result=Agent(FunctionModel(respond),retries=0).run_sync('Continue',message_history=parsed)
assert result.output=='continued' and len(calls)==1
finder.verify_origins()
print(json.dumps({'refusals':refusals,'continuation_calls':len(calls),'preserved_image':True}))
