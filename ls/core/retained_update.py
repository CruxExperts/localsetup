"""Keep retained repository clients out of fresh adapter-path inference."""
import json
from pathlib import Path

from .client_registry import load_client_registry
from .personal_update import _build_recorded_plan


def retained_repository_plan(source: Path, home: Path, target: Path):
    receipt = target / '.localsetup/lock.json'
    if not receipt.exists():
        receipt = target / 'localsetup.lock.json'
    if not receipt.exists():return None
    lock = json.loads(receipt.read_text())
    if not isinstance(lock, dict) or lock.get('skill_scope', 'repo') != 'repo':return None
    preferred_clients = recorded_preferred_path_clients(source, lock, target)
    if not (retained_repository_clients(source, lock) or preferred_clients):return None
    if preferred_clients and 'adapter_targets' not in lock:
        raise ValueError('Legacy recorded adapters require recorded-path manual recovery before update')
    # The existing builder validates recorded paths, health and receipt/registry hashes.
    return _build_recorded_plan(source, home, target, 'repo')


def retained_repository_clients(source: Path, lock: dict) -> list[str]:
    clients = lock.get('platforms', [])
    if not isinstance(clients, list):return []
    retained = {v.variant_id for v in load_client_registry(source).variants()
                if v.data.get('integration', {}).get('lifecycle') == 'retained-only'}
    return [client for client in clients if isinstance(client, str) and client in retained]


def recorded_preferred_path_clients(source: Path, lock: dict, target: Path) -> list[str]:
    """Find recorded repo owners whose paths precede a preferred-write change.

    This only selects preservation routing. The recorded builder validates
    receipt health, ownership and paths before dispatching a mutation.
    """
    clients = lock.get('platforms', lock.get('tools', []))
    if not isinstance(clients, list):return []
    legacy_paths = []
    if not any(key in lock for key in ('platforms', 'tools', 'adapter_targets')):
        for field in ('adapter_state', 'adapter_paths'):
            values = lock.get(field, [])
            if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
                raise ValueError('Legacy adapter paths require review')
            legacy_paths.extend(value.replace('\\', '/') for value in values)
    preferred = {}
    for variant in load_client_registry(source).variants():
        compatibility = variant.data.get('compatibility', {})
        paths = compatibility.get('repo_write_paths')
        client = compatibility.get('platform_id')
        discovered = variant.data['skills']['repo']['paths']
        relative_legacy = []
        for value in legacy_paths:
            candidate = Path(value)
            try:
                relative = candidate.relative_to(target) if candidate.is_absolute() else candidate
            except ValueError:
                continue
            if '..' not in relative.parts:
                relative_legacy.append(relative.as_posix().strip('/'))
        legacy_match = any(value == path.strip('/') or value.startswith(path.strip('/') + '/')
                           for value in relative_legacy for path in discovered)
        if paths is not None and (client in clients or legacy_match):
            preferred[client] = {str((target / path).absolute()) for path in paths}
    if not preferred:return []
    if 'adapter_targets' not in lock:
        # Legacy inference is not a validated reconstruction of physical ownership.
        # Explicit modern empty lists deliberately do not fall back to these fields.
        return sorted(preferred)
    rows = lock.get('adapter_targets', [])
    if not isinstance(rows, list):raise ValueError('Recorded adapters require path review')
    changed = set()
    for row in rows:
        if not isinstance(row, dict):raise ValueError('Recorded adapters require path review')
        owners = row.get('owners', [])
        if not isinstance(owners, list) or any(not isinstance(o, dict) for o in owners):
            raise ValueError('Recorded adapter owners require review')
        names = row.get('platforms') or ([row['platform']] if row.get('platform') else [])
        if not isinstance(names, list) or any(not isinstance(n, str) for n in names):
            raise ValueError('Recorded adapter clients require review')
        if any(not isinstance(o.get('client'), str) for o in owners):
            raise ValueError('Recorded adapter clients require review')
        names = set(names) | {o['client'] for o in owners}
        affected = names.intersection(preferred)
        if not affected:continue
        path = row.get('path')
        if not isinstance(path, str) or not path:raise ValueError('Recorded adapter path requires review')
        absolute = str((target / path).absolute())
        changed.update(client for client in affected if absolute not in preferred[client])
    return sorted(changed)
