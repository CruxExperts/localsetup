"""Versioned provider-free worker probe messages and strict event ordering."""
from __future__ import annotations

import json

MAX_REQUEST = 4096
MAX_OUTPUT = 1024 * 1024
MAX_DIAGNOSTICS = 64 * 1024


def _decode(raw: bytes):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Duplicate worker protocol key')
            value[key] = item
        return value
    return json.loads(raw, object_pairs_hook=unique)


def probe_request(raw: bytes) -> None:
    value = _decode(raw) if len(raw) <= MAX_REQUEST else None
    if not isinstance(value, dict) or type(value.get('schema_version')) is not int or value != {'schema_version': 1, 'operation': 'probe'}:
        raise ValueError('Unsupported worker request')


def event(sequence: int, kind: str, data: dict) -> bytes:
    return (json.dumps({'schema_version': 1, 'sequence': sequence, 'type': kind, 'data': data}, sort_keys=True) + '\n').encode()


def result(raw: bytes) -> dict:
    lines = raw.splitlines()
    if len(lines) != 2:
        raise ValueError('Worker must emit ready and result exactly once')
    values = [_decode(line) for line in lines]
    for sequence, (value, kind) in enumerate(zip(values, ('ready', 'result'))):
        if not isinstance(value, dict) or set(value) != {'schema_version', 'sequence', 'type', 'data'} or type(value['schema_version']) is not int or value['schema_version'] != 1 or type(value['sequence']) is not int or value['sequence'] != sequence or value['type'] != kind or not isinstance(value['data'], dict):
            raise ValueError('Invalid worker event schema or sequence')
    if values[0]['data'] != {}:
        raise ValueError('Unexpected worker ready payload')
    data = values[1]['data']
    if set(data) != {'schema_version', 'status', 'origins'} or type(data['schema_version']) is not int or data['schema_version'] != 1 or data['status'] != 'qualified' or not isinstance(data['origins'], dict) or not data['origins'] or any(not isinstance(k, str) or not isinstance(v, str) for k, v in data['origins'].items()):
        raise ValueError('Invalid worker qualification result')
    return data
