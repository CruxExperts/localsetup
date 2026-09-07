"""Isolated native history reconstruction; callers own evidence and authority checks."""
from __future__ import annotations

import json
import sys

from .checkpoint_store import MAX_MESSAGES
from .tool_results import MAX_RESULT, _digest, _validate


def reconstruct(finder, history: bytes, receipts: list, *, recipes: dict) -> bytes:
    """Append settled returns without executing tools or contacting a provider.

    The supervisor must validate every receipt against its journal/checkpoint,
    bind the history and recipe inventory, and persist a new current checkpoint.
    This pure worker helper grants no authority and never changes old evidence.
    """
    if not sys.flags.isolated or not sys.dont_write_bytecode or sys.meta_path[0] is not finder:
        raise RuntimeError('SDK recovery requires the active isolated worker importer')
    finder.verify_origins()
    if not isinstance(history, bytes) or len(history) > MAX_MESSAGES:
        raise ValueError('Recovery requires bounded serialized history')
    if not isinstance(receipts, list) or not 1 <= len(receipts) <= 256 or len(json.dumps(receipts, allow_nan=False).encode()) > MAX_MESSAGES:
        raise ValueError('Recovery requires bounded tool receipts')
    if not isinstance(recipes, dict) or len(recipes) > 64:
        raise ValueError('Recovery requires an explicit bounded recipe inventory')
    from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart, RetryPromptPart
    messages = ModelMessagesTypeAdapter.validate_json(history)
    pending, seen = {}, set()
    for message in messages:
        if isinstance(message, ModelResponse) and pending:
            raise ValueError('History advanced past unresolved tool calls')
        for part in message.parts:
            if isinstance(part, ToolCallPart):
                if not part.tool_call_id or part.tool_call_id in seen:
                    raise ValueError('History has ambiguous tool call identities')
                seen.add(part.tool_call_id)
                pending[part.tool_call_id] = part
            elif isinstance(part, (ToolReturnPart, RetryPromptPart)) and part.tool_call_id:
                call = pending.pop(part.tool_call_id, None)
                if call is None or part.tool_name != call.tool_name:
                    raise ValueError('History has unmatched tool result identity')
    if not pending:
        raise ValueError('History has no unresolved tool calls')
    verified = {}
    identity = None
    for receipt in receipts:
        _validate(receipt)
        if len(json.dumps(receipt, allow_nan=False).encode()) > MAX_RESULT:
            raise ValueError('Recovery receipt exceeds limit')
        call = receipt['tool_call']
        bound = (receipt['task'], receipt['session'], receipt['profile'], call['run_id'])
        if identity is not None and identity != bound:
            raise ValueError('Recovery receipts have different identities')
        identity = bound
        part = pending.get(call['call_id'])
        if part is None or call['call_id'] in verified or part.tool_name != call['name']:
            raise ValueError('Receipt does not match one pending tool call')
        arguments = part.args_as_dict()
        result = receipt['result']
        if part.tool_name == 'write_file':
            if set(arguments) != {'path', 'content', 'expected_before'} or set(result) != {'operation', 'status'} or result['status'] not in ('applied', 'not_applied'):
                raise ValueError('Invalid recovered file call or result')
        elif part.tool_name == 'run_command':
            if set(arguments) != {'name'} or not isinstance(arguments['name'], str) or arguments['name'] not in recipes:
                raise ValueError('Recovery requires the original named process recipe')
            recipe = recipes[arguments['name']]
            from .process_rpc import Recipe
            if not isinstance(recipe, Recipe):
                raise ValueError('Recovery recipe must be a validated supervisor recipe')
            arguments = {'name': arguments['name'], 'command': recipe.command, 'files': recipe.files, 'seconds': recipe.seconds}
            if set(result) != {'operation', 'status', 'returncode', 'output'} or result['status'] not in ('completed', 'failed', 'cancelled', 'timed_out', 'output_limit'):
                raise ValueError('Invalid recovered process result')
        else:
            raise ValueError('Pending tool has no qualified recovery implementation')
        if _digest(arguments) != call['arguments_sha256']:
            raise ValueError('Pending tool arguments differ from operation evidence')
        verified[call['call_id']] = result
    if set(verified) != set(pending):
        raise ValueError('Unresolved tool calls lack durable results; do not replay')
    returned = [ToolReturnPart(tool_name=part.tool_name, tool_call_id=call_id, content=verified[call_id])
                for call_id, part in pending.items()]
    messages.append(ModelRequest(parts=returned))
    result = ModelMessagesTypeAdapter.dump_json(messages)
    if len(result) > MAX_MESSAGES:
        raise ValueError('Recovered history exceeds byte limit')
    finder.verify_origins()
    return result
