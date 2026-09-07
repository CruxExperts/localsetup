"""Retire one target's personal association without removing other references."""
import copy
from pathlib import Path

from .detach_records import recorded_detach_rows
from .installation_ownership import InstallationOwner
from .lockfile import load_json
from .manifests import load_pack_config
from .paths import expand_user_path, target_lockfile_path
from .personal_detach import _execute, _plan, _without_owners
from .personal_registry import owner_key, personal_selections
from .personal_update import build_recorded_both_plan
from .registry import load_registry


def _keys(adapters):
    return {key for row in adapters for key in personal_selections(row)}


def _retirement_plan(source, home, target):
    recorded = build_recorded_both_plan(source, home, target)
    receipt = target_lockfile_path(target)
    lock = load_json(receipt)
    repository = recorded_detach_rows(lock, target)
    clients = sorted({c for _, _, owners in repository for c in owners})
    if not clients:raise ValueError('Personal scope retirement requires retained repository owners')
    selected = _keys(lock.get('personal_adapter_targets', []))
    if not selected:raise ValueError('No recorded personal associations to retire')
    registry_path = expand_user_path(load_pack_config(source).global_registry, home)
    registry = load_registry(registry_path)
    target_id = str(target.resolve())
    association = registry['targets'].get(target_id)
    if not association or association.get('lock_path') != str(receipt):
        raise ValueError('Target registry association does not match receipt')
    if _keys(association.get('adapters', [])) != selected:
        raise ValueError('Personal ownership differs between target registry and receipt')
    retained = selected & {key for root, row in registry['targets'].items() if root != target_id
                           for key in _keys(row.get('adapters', []))}
    exclusive = selected - retained
    owner_clients = {owner_key(InstallationOwner(**o)): o['client']
                     for row in lock['personal_adapter_targets'] for o in row['owners']}
    payload, actions, registry_path, updated, receipts = _plan(source, home, [owner_clients[k] for k in sorted(exclusive)])
    if not payload['ok']:raise ValueError('; '.join(payload['blockers']))
    if set(receipts) - {receipt}:
        raise ValueError('Exclusive personal retirement unexpectedly affects another receipt')
    replacement = copy.deepcopy(lock)
    replacement['personal_adapter_targets'] = []
    replacement['platforms'] = clients
    replacement['skill_scope'] = 'repo'
    receipts[receipt] = replacement
    updated['targets'][target_id]['adapters'] = _without_owners(association['adapters'], selected)
    payload.update(auto_mode='retire_personal_scope', target_root=target_id,
                   **{'from': 'both', 'to': 'repo'},
                   detached_associations=sorted(selected), retained_owners=sorted(retained),
                   receipts=[str(receipt)], recorded_state_hashes=recorded.rollback_metadata['recorded_state_hashes'])
    return payload, actions, registry_path, updated, receipts


def retire_personal_scope(source: Path, home: Path, target: Path, *, apply: bool = False,
                          expected: dict | None = None) -> dict:
    def planner():
        result = _retirement_plan(source, home, target)
        if expected is not None and result[0] != expected:
            raise ValueError('stale_scope_retirement: recorded ownership changed')
        return result
    return _execute(source, home, planner, apply=apply, operation='personal-scope-retirement',
                    require_unchanged=True)
