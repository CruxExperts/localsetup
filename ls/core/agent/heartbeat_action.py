"""Provider-free heartbeat action bindings from explicit private controller inputs."""
import hashlib
import os
from pathlib import Path
import threading
import time

from . import heartbeat_budget as budget
from . import registration_owner as files
from .broker_rpc import _decode
from .coding_protocol import profile_digest
from .file_grants import FileGrant
from .process_rpc import Recipe
from .profile_setup import _parent
from .profiles import parse, wire
from .registration_dispatch import resolve
from .session_owner import _separate

PATHS = ('executable', 'profiles', 'grant', 'runtime_root', 'state_root', 'resource_parent')


def path(value):
    if not isinstance(value, str) or not value or '\0' in value:
        raise ValueError('Action paths require canonical absolute strings')
    result = Path(value)
    if not result.is_absolute() or '..' in result.parts or str(result) != value:
        raise ValueError('Action paths require canonical absolute strings')
    return result


def read(source, workspace):
    _separate(source, workspace)
    fd = _parent(source, create=False)
    if fd is None:
        raise FileNotFoundError('Action input is missing')
    try:
        raw = files._read(fd, source.name)
    finally:
        os.close(fd)
    if raw is None:
        raise FileNotFoundError('Action input is missing')
    return raw, _decode(raw)


def _grant(value, workspace, task, session):
    budget._keys(value, {'schema_version', 'read', 'write', 'disclose', 'recipes'})
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ValueError('Unsupported action grant schema')
    for key in ('read', 'write', 'disclose'):
        if not isinstance(value[key], list) or len(value[key]) > 256:
            raise ValueError('Invalid action file scopes')
    FileGrant(task, session, workspace, *(tuple(value[k]) for k in ('read', 'write', 'disclose')),
              time.monotonic()+1, threading.Event())
    if not isinstance(value['recipes'], dict) or len(value['recipes']) > 64:
        raise ValueError('Invalid action recipes')
    for name, recipe in value['recipes'].items():
        budget._identity(name, budget.IDENTIFIER)
        budget._keys(recipe, {'command', 'files', 'seconds'})
        if not isinstance(recipe['command'], list) or not isinstance(recipe['files'], list):
            raise ValueError('Invalid action recipe')
        Recipe(tuple(recipe['command']), tuple(recipe['files']), recipe['seconds'])


def plan(source: Path, workspace: Path, accounting_root: Path) -> dict:
    source, workspace, accounting_root = map(lambda item: path(str(item)), (source, workspace, accounting_root))
    _, value = read(source, workspace)
    budget._keys(value, {'schema_version', 'operation', 'task', 'session', 'checkpoint', 'profile',
                        'prompt', 'run', 'compact', 'idle_seconds', 'output_bytes', *PATHS})
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ValueError('Unsupported action schema')
    for key in ('operation', 'task', 'session'):
        budget._identity(value[key], budget.IDENTIFIER)
    if value['checkpoint'] is not None:
        budget._identity(value['checkpoint'], budget.DIGEST)
    prompt, name = value['prompt'], value['profile']
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode()) > 131072:
        raise ValueError('Action prompt must be bounded nonempty UTF-8')
    if not isinstance(name, str) or not 1 <= len(name) <= 256 or '\0' in name:
        raise ValueError('Action requires an explicit provider profile')
    compact = value['compact']
    if compact is not None:
        budget._keys(compact, {'tokens', 'seconds', 'keep_messages', 'disclose_history'})
        if value['checkpoint'] is None or compact['disclose_history'] is not True:
            raise ValueError('Compaction requires explicit checkpoint disclosure')
        if type(compact['keep_messages']) is not int or not 0 <= compact['keep_messages'] <= 256:
            raise ValueError('Invalid retained message limit')
        budget._integer(compact['tokens'], 1, 1000000)
    allocation = None if compact is None else {key: compact[key] for key in ('tokens', 'seconds')}
    envelope = budget.envelope(value['run'], allocation)
    for phase in (value['run'], allocation):
        if phase is not None and not 21 <= phase['seconds'] <= 3620:
            raise ValueError('Phase allocation includes 20 seconds of startup and cleanup')
    for key, low, high in (('idle_seconds', 1, value['run']['seconds']-20),
                           ('output_bytes', 1024, 4194304)):
        if type(value[key]) is not int or not low <= value[key] <= high:
            raise ValueError('Invalid action process limit')
    paths = {key: path(value[key]) for key in PATHS}
    for item in (accounting_root, *paths.values()):
        _separate(item, workspace)
    # Runtime/session mutations cannot overwrite the controller's inputs or receipts.
    for root in (paths['runtime_root'], paths['state_root'], paths['resource_parent']):
        for control in (source, accounting_root, paths['profiles'], paths['grant'], paths['executable']):
            _separate(root, control)
    _separate(paths['runtime_root'], paths['state_root'])
    _separate(source, accounting_root)
    grant_raw, grant = read(paths['grant'], workspace)
    _grant(grant, workspace, value['task'], value['session'])
    profile_raw, document = read(paths['profiles'], workspace)
    budget._keys(document, {'schema_version', 'profiles'})
    if type(document['schema_version']) is not int or document['schema_version'] != 1 or not isinstance(document['profiles'], dict):
        raise ValueError('Unsupported action provider document')
    profile = parse(document['profiles'][name])
    if not {'tools', 'streaming'} <= profile.capabilities:
        raise ValueError('Coding profile requires tools and streaming')
    command = resolve(paths['executable'], paths['runtime_root'])
    material = {'schema_version': 1, 'workspace': str(workspace), 'accounting_root': str(accounting_root),
                'action': value, 'launcher': command, 'grant_sha256': hashlib.sha256(grant_raw).hexdigest(),
                'profiles_sha256': hashlib.sha256(profile_raw).hexdigest()}
    binding = hashlib.sha256(files.encode(material)).hexdigest()
    return {'schema_version': 1, 'operation': value['operation'], 'binding': binding,
            'authorization': {'binding': binding, 'run': value['run'], 'compact': allocation},
            'envelope': envelope, 'profile_sha256': profile_digest(wire(profile)),
            'action': 'run' if compact is None else 'compact_then_run',
            'checkpoint': value['checkpoint'], 'task': value['task'], 'session': value['session']}
