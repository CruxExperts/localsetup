"""Native message reconstruction and continuation without tool replay."""
import asyncio
import json
from pathlib import Path
import sys

if len(sys.argv) == 2:
    sys.path.insert(0, sys.argv[1]); payload = Path(sys.argv[1])/'vendor/lscli'
else:
    import ls
    payload = Path(ls.__file__).parent/'_sdk_payload'
from ls.core.agent.sdk_imports import activate
finder = activate(payload)
from ls.core.agent.sdk_recovery import reconstruct
from ls.core.agent.tool_results import _digest
from ls.core.agent.process_rpc import Recipe
from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelResponse, ModelRequest, UserPromptPart, ToolCallPart, ToolReturnPart
from pydantic_ai import Agent
from pydantic_ai.models.function import FunctionModel

args = {'path':'src/a.txt', 'content':'changed', 'expected_before':None}
recipe = Recipe(('/usr/bin/true',), ('src/a.txt',), 2)
expanded = {'name':'test', 'command':recipe.command, 'files':recipe.files, 'seconds':recipe.seconds}
messages = [ModelRequest(parts=[UserPromptPart('edit and test')]), ModelResponse(parts=[
    ToolCallPart('write_file', args, 'write'), ToolCallPart('run_command', {'name':'test'}, 'test')])]
history = ModelMessagesTypeAdapter.dump_json(messages)
def receipt(name, call_id, arguments, result):
    return {'schema_version':1, 'task':'task', 'session':'session', 'profile':'a'*64, 'checkpoint':'b'*64,
            'tool_call':{'run_id':'run','call_id':call_id,'name':name,'arguments_sha256':_digest(arguments)}, 'result':result}
receipts = [receipt('write_file','write',args,{'operation':'c'*32,'status':'applied'}),
            receipt('run_command','test',expanded,{'operation':'d'*32,'status':'completed','returncode':0,'output':{'stdout':'passed','stderr':''}})]
restored = reconstruct(finder, history, receipts, recipes={'test':recipe})
parsed = ModelMessagesTypeAdapter.validate_json(restored)
assert ModelMessagesTypeAdapter.dump_json(parsed[:-1]) == history
assert len(parsed[-1].parts) == 2 and all(isinstance(x,ToolReturnPart) for x in parsed[-1].parts)
assert parsed[-1].parts[1].content['output']['stdout'] == 'passed'
rejected = 0
for records, recipes in [(receipts[:1], {'test':recipe}), (receipts+receipts[:1], {'test':recipe}),
                         (receipts, {}), (receipts, {'test':Recipe(('/usr/bin/false',),('src/a.txt',),2)}),
                         ([receipts[0]|{'profile':'e'*64},receipts[1]], {'test':recipe}),
                         ([receipts[0]|{'tool_call':receipts[0]['tool_call']|{'arguments_sha256':'f'*64}},receipts[1]], {'test':recipe})]:
    try: reconstruct(finder,history,records,recipes=recipes)
    except ValueError: rejected += 1
    else: raise AssertionError('invalid recovery accepted')
assert rejected == 6
calls = []
def response(history, info):
    assert any(isinstance(p,ToolReturnPart) and p.tool_call_id=='test' for m in history for p in m.parts)
    calls.append('model')
    from pydantic_ai.messages import TextPart
    return ModelResponse(parts=[TextPart('recovered without replay')])
async def main():
    result = await Agent(FunctionModel(response), retries=0).run('Continue.',message_history=parsed)
    assert result.output == 'recovered without replay' and calls == ['model']
asyncio.run(main())
print(json.dumps({'recovered_calls':2,'refusals':rejected,'continuation_calls':len(calls),'origins':finder.verify_origins()}))
