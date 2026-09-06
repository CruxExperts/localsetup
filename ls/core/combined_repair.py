"""Repair recorded repository and personal adapters in one transaction."""
import os
import uuid
from pathlib import Path

from .adapter_markers import ADAPTER_MARKER_JSON, adapter_marker_state, adapter_marker_packages, is_safe_adapter_package_name
from .adapters import adapter_path_state
from .personal_inventory import _links
from .apply_journal import write_journal, restore_failed_mutations, cleanup_backups
from .lockfile import load_json
from .locking import package_root_lock
from .manifests import load_pack_config
from .models import PlanAction
from .paths import expand_user_path, global_layout
from .personal_adapter import check_path, managed_entry, selection, write_entries
from .personal_repair import _plan as personal_plan
from .provenance import is_managed_package, package_digest
from .registry import load_registry


def _clients(row):
    if 'owners' in row:return {o['client'] for o in row['owners']}
    return set(row.get('platforms') or ([row['platform']] if row.get('platform') else []))


def _needs_repair(boundary, action, names):
    check_path(action.path, boundary)
    mode = action.details['mode'];library = Path(action.details['global_root'])
    if mode not in {'symlink', 'portable'}:raise ValueError('Invalid recorded adapter mode')
    if any(not isinstance(n, str) or not is_safe_adapter_package_name(n) for n in names):
        raise ValueError('Invalid recorded adapter package selection')
    marker = action.path / ADAPTER_MARKER_JSON
    if marker.is_symlink() or (marker.exists() and not marker.is_file()):
        raise ValueError('Unsafe adapter marker')
    state = adapter_marker_state(action.path)
    if state['error']:raise ValueError('Adapter marker requires preservation review')
    visible = set(adapter_path_state(action.path, library).get('managed_visible_packages', []))
    if visible - set(names) - (adapter_marker_packages(action.path) or set()):
        raise ValueError('Unrecorded managed adapter entries require preservation review')
    dirty = state['mode'] != mode or adapter_marker_packages(action.path) != set(names) or visible != set(names)
    for name in names:
        source = library / name;entry = action.path / name
        if not source.is_dir() or not is_managed_package(source):
            raise ValueError(f'Reinstall missing managed library package: {name}')
        if entry.exists() or entry.is_symlink():
            if not managed_entry(entry, library, state['mode']):
                raise ValueError(f'Custom adapter package collision: {entry}')
            if mode == 'portable' and (package_digest(entry) != package_digest(source) or _links(entry) != _links(source)):dirty = True
        else:dirty = True
    return dirty


def _plan(source, home, target, clients):
    lock = load_json(target / '.localsetup/lock.json')
    if lock.get('skill_scope') != 'both':raise ValueError('Combined repair requires a current both-scope receipt')
    pack = load_pack_config(source);library = expand_user_path(pack.global_root, home)
    registry = load_registry(expand_user_path(pack.global_registry, home))
    personal_clients = {o['client'] for row in lock.get('personal_adapter_targets', []) for o in row.get('owners', [])}
    requested = set(lock.get('platforms', [])) if clients is None else set(clients)
    personal, personal_actions = personal_plan(source, home, sorted(requested & personal_clients))
    blockers = list(personal['blockers'])
    blockers.extend(f'No recorded repair client: {c}' for c in sorted(requested - set(lock.get('platforms', []))))
    actions = {}
    try:
        for action in personal_actions:
            names = selection(source, home, action)
            actions[str(action.path)] = (home, action, names)
        for row in lock.get('adapter_targets', []):
            if not requested.intersection(_clients(row)):continue
            path = Path(row['path'])
            if not path.is_absolute():path = target / path
            mode = row.get('mode', lock.get('attach_mode', 'symlink'))
            names = set(row.get('packages', lock.get('repo_packages', [])))
            for owner in registry.get('personal_owners', {}).values():
                if str(path) in owner['paths']:
                    if owner['mode'] != mode:raise ValueError('Shared adapter owner mode conflict')
                    names.update(owner['packages'])
            for record in registry['targets'].values():
                for adapter in record.get('adapters', []):
                    repo_owned = any(o.get('scope') == 'repo' for o in adapter.get('owners', [])) if 'owners' in adapter else bool(_clients(adapter))
                    if repo_owned and adapter.get('path') == str(path):
                        if adapter.get('mode', 'symlink') != mode:raise ValueError('Shared adapter owner mode conflict')
                        names.update(adapter.get('packages', []))
            action = PlanAction('repair_repo_path', path, {'mode': mode, 'packages': sorted(names), 'global_root': str(library), 'platforms': sorted(_clients(row))})
            dirty = _needs_repair(target, action, names)
            previous = actions.get(str(path))
            if previous and (set(previous[2]) != names or previous[1].details['mode'] != mode):
                raise ValueError('Shared repair selections disagree')
            if dirty:actions[str(path)] = (target, action, sorted(names))
        for boundary, action, names in actions.values():_needs_repair(boundary, action, names)
    except (ValueError, OSError, TypeError, KeyError) as exc:blockers.append(str(exc))
    from .amp_preflight import amp_skill_blockers
    blockers.extend(b['reason'] for b in amp_skill_blockers(source, [a for _, a, _ in actions.values()], home, target))
    from .goose_prerequisite import goose_prerequisite_blockers
    blockers.extend(b['reason'] for b in goose_prerequisite_blockers(source, [a for _, a, _ in actions.values()], home, target))
    return {'ok': not blockers, 'applied': False, 'blockers': blockers,
            'actions': [{'kind': a.kind, 'path': str(a.path), 'details': a.details} for _, a, _ in actions.values()],
            'verification': {'ok': not blockers and not actions, 'owners': personal['verification']['owners'],
                             'personal': personal['verification']}}, list(actions.values())


def repair_combined(source: Path, home: Path, target: Path, clients=None, *, apply=False):
    payload, actions = _plan(source, home, target, clients)
    if not apply or not payload['ok'] or not actions:return payload
    state = global_layout(home).localsetup_home
    with package_root_lock(state):
        payload, actions = _plan(source, home, target, clients)
        if not payload['ok'] or not actions:return payload
        path = state / 'state/combined-repair' / (uuid.uuid4().hex + '.json')
        journal = {'version': 1, 'status': 'started', 'operation': 'combined-repair', 'touched': []}
        try:
            for boundary, action, names in actions:write_entries(boundary, action, names, journal, path)
            checked, remaining = _plan(source, home, target, clients)
            if not checked['ok'] or remaining:raise ValueError('Combined repair verification failed')
            journal['status'] = 'committed';write_journal(path, journal)
        except Exception as exc:
            journal['status'] = 'failed'
            try:restore_failed_mutations(journal, os.replace)
            except Exception as recovery:journal['rollback_error'] = str(recovery)
            write_journal(path, journal)
            return payload | {'ok': False, 'blockers': [str(exc)], 'journal': str(path),
                              'recovery_ok': 'rollback_error' not in journal}
        warnings = []
        try:cleanup_backups(journal)
        except OSError as exc:warnings.append(f'combined repair committed; backup cleanup failed: {exc}')
        return payload | {'applied': True, 'verification': checked['verification'], 'journal': str(path), 'warnings': warnings}
