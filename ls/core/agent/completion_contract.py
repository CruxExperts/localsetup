"""Provider-free version-one tool-free completion validation and outcomes."""
from dataclasses import dataclass
import math
from urllib.parse import unquote

from .broker_rpc import _decode, _encode
from .profiles import REASONING_EFFORTS

MAX_REQUEST = 1024 * 1024
MAX_OUTPUT = 1024 * 1024
EXITS = {'succeeded': 0, 'invalid_request': 2, 'unavailable': 3,
         'refused': 4, 'incomplete': 5, 'malformed': 6, 'schema_rejected': 7,
         'rate_limited': 8, 'transport_failed': 9, 'uncertain': 10,
         'provider_error': 11, 'output_limit': 12, 'deadline': 124, 'cancelled': 130}


@dataclass(frozen=True)
class Request:
    model: str
    reasoning_effort: str | None
    deadline_seconds: float
    max_output_tokens: int
    input: object
    output_schema: dict
    schema_mode: str
    temperature: float | None = None
    schema_name: str = "completion"


def validator(schema):
    """Draft 2020-12, local references only; never retrieve remote schemas."""
    from jsonschema import Draft202012Validator
    if not isinstance(schema, dict):
        raise ValueError('Output schema must be an object')
    stack = [(schema, 0)]
    while stack:
        value, depth = stack.pop()
        if depth > 64: raise ValueError('Schema nesting exceeds limit')
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ('$id', '$schema'):
                    if key == '$schema' and item == 'https://json-schema.org/draft/2020-12/schema': continue
                    raise ValueError('Schema identifiers are not supported')
                if key in ('$ref', '$dynamicRef'):
                    if not isinstance(item, str) or not (item == '#' or item.startswith('#/')):
                        raise ValueError('Only local JSON Pointer schema references are supported')
                    target = schema
                    try:
                        for part in unquote(item[1:])[1:].split('/') if item != '#' else []:
                            part = part.replace('~1', '/').replace('~0', '~')
                            target = target[int(part)] if isinstance(target, list) else target[part]
                    except (KeyError, IndexError, ValueError, TypeError):
                        raise ValueError('Unresolved local schema reference') from None
                    if not isinstance(target, (dict, bool)):
                        raise ValueError('Schema reference target is not a schema')
                stack.append((item, depth + 1))
        elif isinstance(value, list):
            stack.extend((item, depth + 1) for item in value)
    from jsonschema.exceptions import SchemaError
    try: Draft202012Validator.check_schema(schema)
    except SchemaError: raise ValueError('Invalid output schema') from None
    return Draft202012Validator(schema)


def parse(raw: bytes, profile) -> Request:
    if not isinstance(raw, bytes) or len(raw) > MAX_REQUEST:
        raise ValueError('Completion request exceeds byte limit')
    value = _decode(raw)
    required = {'interface_version', 'model', 'deadline_seconds', 'max_attempts',
                'max_output_tokens', 'input', 'output_schema'}
    if not isinstance(value, dict) or not required <= set(value) or set(value) - required - {'reasoning_effort', 'schema_mode', 'temperature', 'schema_name'}:
        raise ValueError('Completion request fields differ from version one')
    if type(value['interface_version']) is not int or value['interface_version'] != 1:
        raise ValueError('Unsupported completion interface version')
    if value['model'] != profile.model: raise ValueError('Request model differs from selected profile')
    if type(value['max_attempts']) is not int or value['max_attempts'] != 1:
        raise ValueError('Completion permits exactly one attempt')
    deadline = value['deadline_seconds']
    if type(deadline) not in (int, float) or not 0 < deadline <= 3600 or not math.isfinite(deadline):
        raise ValueError('Invalid completion deadline')
    tokens = value['max_output_tokens']
    if type(tokens) is not int or not 1 <= tokens <= 1000000:
        raise ValueError('Invalid completion token limit')
    effort = value.get('reasoning_effort')
    if effort is not None and (not isinstance(effort,str) or effort not in REASONING_EFFORTS):
        raise ValueError('Invalid reasoning effort')
    if effort is not None and 'reasoning:' + effort not in profile.capabilities:
        raise ValueError('Selected profile does not qualify this reasoning effort')
    mode = value.get('schema_mode', 'native')
    if mode not in ('native', 'validate_only'):
        raise ValueError('Invalid schema mode')
    if mode == 'native' and 'native_schema' not in profile.capabilities:
        raise ValueError('Selected profile does not qualify native schema enforcement')
    temperature=value.get('temperature')
    if temperature is not None and (type(temperature) not in (int,float) or not 0<=temperature<=2 or not math.isfinite(temperature) or 'temperature' not in profile.capabilities):
        raise ValueError('Unqualified or invalid completion temperature')
    import re
    name=value.get('schema_name','completion')
    if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',name):raise ValueError('Invalid schema name')
    validator(value['output_schema'])
    return Request(profile.model, effort, float(deadline), tokens, value['input'], value['output_schema'], mode,temperature,name)


def validate_output(text: str, request: Request):
    if not isinstance(text, str): return 'malformed', None
    try: raw = text.encode()
    except UnicodeError: return 'malformed', None
    if len(raw) > MAX_OUTPUT: return 'output_limit', None
    try: value = _decode(raw)
    except (ValueError, UnicodeError, RecursionError): return 'malformed', None
    from referencing.exceptions import Unresolvable
    try:
        if not validator(request.output_schema).is_valid(value): return 'schema_rejected', None
    except (ValueError, RecursionError, Unresolvable): return 'schema_rejected', None
    return 'succeeded', value


def envelope(status, *, model=None, data=None, usage=None, request_id=None, attempts=0):
    if status not in EXITS or type(attempts) is not int or attempts not in (0, 1):
        raise ValueError('Invalid completion outcome')
    if status != 'succeeded': data = None
    result = {'interface_version': 1, 'status': status, 'data': data, 'model': model,
              'usage': usage, 'request_id': request_id, 'attempts': attempts, 'reason': status}
    if len(_encode(result)) > MAX_OUTPUT + 4096: raise ValueError('Completion envelope exceeds byte limit')
    return result
