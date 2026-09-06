"""Join a retained execution receipt to its unresolved accounting reservation."""
import hashlib
import math
import os
from pathlib import Path
import time

from . import heartbeat_action as action
from . import heartbeat_budget as budget
from . import heartbeat_budget_store as store
from . import heartbeat_execution as execution
from .session_owner import _private, lease


def _evidence(raw, plan, value):
    evidence = store._parse(raw)
    budget._keys(evidence, {'schema_version', 'operation', 'binding', 'outcome',
                          'phases', 'checkpoint', 'elapsed_seconds'})
    if (type(evidence['schema_version']) is not int or evidence['schema_version'] != 1 or
            evidence['operation'] != value['operation'] or evidence['binding'] != plan['binding']):
        raise ValueError('Retained result identity differs from the action')
    if evidence['outcome'] not in ('execution_completed', 'failed', 'cancelled', 'timed_out', 'output_limit'):
        raise ValueError('Unknown retained outcome')
    elapsed = evidence['elapsed_seconds']
    if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0:
        raise ValueError('Invalid retained duration')
    if evidence['checkpoint'] is not None:
        budget._identity(evidence['checkpoint'], budget.DIGEST)
    kinds = ['compact', 'run'] if value['compact'] is not None else ['run']
    phases = evidence['phases']
    if not isinstance(phases, list) or len(phases) > len(kinds):
        raise ValueError('Invalid retained phases')
    for index, phase in enumerate(phases):
        budget._keys(phase, {'kind', 'process'})
        if phase['kind'] != kinds[index] or not isinstance(phase['process'], dict):
            raise ValueError('Retained phase order differs from the action')
        process = phase['process']
        if type(process.get('returncode')) is not int or 'protocol' not in process:
            raise ValueError('Retained process lacks a terminal result')
        if any(key.endswith('_tail') for key in process):
            raise ValueError('Retained result contains raw process tails')
    if evidence['outcome'] == 'execution_completed':
        if len(phases) != len(kinds) or evidence['checkpoint'] is None:
            raise ValueError('Completed result requires all phases and checkpoint')
        for phase in phases:
            process = phase['process']
            protocol = process['protocol']
            if process['returncode'] != 0 or not isinstance(protocol, dict) or protocol.get('completed') is not True:
                raise ValueError('Completed result lacks successful process and protocol')
        protocol = phases[-1]['process']['protocol']
        budget._keys(protocol, {'completed', 'status', 'sequence', 'identity', 'checkpoint'})
        if (protocol['status'] != 'completed' or protocol['identity'] !=
                {key: value[key] for key in ('task', 'session', 'profile')} or
                protocol['checkpoint'] != evidence['checkpoint']):
            raise ValueError('Completed coding identity/checkpoint mismatch')
        budget._integer(protocol['sequence'], 2, 4194304)
    return evidence


def _historical(value, workspace, plan, receipt, expires):
    state = Path(value['state_root'])/'sessions'
    root = state/hashlib.sha256(value['session'].encode()).hexdigest()
    for directory in (root, root/'journal', root/'checkpoints'):
        fd = _private(directory)
        try:
            if store.files._read(fd, execution.LOCK_NAME) is None:
                raise FileNotFoundError('Session coordination evidence is missing')
        finally:
            os.close(fd)
    with lease(state, task=value['task'], session=value['session'], workspace=workspace,
               expires=expires, create=False) as owner:
        execution.compaction.verify_history(owner, receipt, source=value['checkpoint'],
            profile=plan['profile_sha256'], token_limit=value['compact']['tokens'])


def reconcile(source, workspace, accounting_root, *, expected_head, expected_binding, expected_result):
    budget._identity(expected_result, budget.DIGEST)
    plan, value, _, profiles, grant = action.prepare(source, workspace, accounting_root)
    if plan['binding'] != expected_binding:
        raise ValueError('Action changed since controller review')
    state = store.inspect(accounting_root, workspace, operation=value['operation'])
    if (state['head'] != expected_head or state['policy']['task'] != value['task'] or
            state['authorization'] != plan['authorization'] or
            state['summary']['pending'] != {'operation': value['operation'], 'result': None}):
        raise ValueError('Reconciliation requires the exact unresolved reservation')
    directory = Path(value['state_root'])/'heartbeat'/expected_binding
    fd = _private(directory)
    try:
        if store.files._read(fd, 'profiles.json') != profiles or store.files._read(fd, 'grant.json') != grant:
            raise ValueError('Retained inputs differ from the reviewed action')
        raw = store.files._read(fd, 'result.json')
    finally:
        os.close(fd)
    if raw is None or hashlib.sha256(raw).hexdigest() != expected_result:
        raise ValueError('Retained result is missing or differs from the reviewed digest')
    evidence = _evidence(raw, plan, value)
    if evidence['outcome'] == 'execution_completed':
        expires = time.monotonic()+5
        if value['compact'] is not None:
            protocol = evidence['phases'][0]['process']['protocol']
            budget._keys(protocol, {'completed', 'receipt'})
            _historical(value, workspace, plan, protocol['receipt'], expires)
        execution._history(value, workspace, plan['profile_sha256'], expires, evidence['checkpoint'])
    result = store.append(accounting_root, workspace,
        dict(type='result', operation=value['operation'], result=expected_result), expected_head)
    return {'schema_version': 1, 'outcome': evidence['outcome'], 'result': expected_result,
            'evidence': str(directory/'result.json'), 'accounting': result}
