"""Retire repository ownership while retaining recorded personal installation."""
from pathlib import Path

from .detach import _detach_platforms_locked
from .detach_records import recorded_detach_rows
from .lockfile import load_json
from .locking import package_root_lock
from .paths import global_layout, target_lockfile_path
from .personal_update import build_recorded_both_plan


def plan_repository_retirement(source: Path, home: Path, target: Path) -> dict:
    recorded = build_recorded_both_plan(source, home, target)
    lock = load_json(target_lockfile_path(target))
    rows = recorded_detach_rows(lock, target)
    if not rows or any(not clients for _, _, clients in rows):
        raise ValueError('Repository scope retirement requires recorded ownership for every adapter')
    if not lock.get('personal_adapter_targets'):
        raise ValueError('Repository scope retirement requires retained personal ownership')
    clients = sorted({client for _, _, owners in rows for client in owners})
    return {'schema_version': 1, 'ok': True, 'applied': False,
            'auto_mode': 'retire_repository_scope', 'from': 'both', 'to': 'personal',
            'target_root': str(target), 'clients': clients,
            'paths': [str(path) for path, _, _ in rows],
            'retained_personal_targets': lock['personal_adapter_targets'],
            'recorded_state_hashes': recorded.rollback_metadata['recorded_state_hashes'],
            'packages_preserved': True}


def retire_repository_scope(source: Path, home: Path, target: Path, *, apply: bool = False,
                            expected: dict | None = None) -> dict:
    plan = plan_repository_retirement(source, home, target)
    if expected is not None and plan != expected:
        raise ValueError('stale_scope_retirement: recorded ownership changed')
    if not apply:return plan
    with package_root_lock(global_layout(home).localsetup_home):
        current = plan_repository_retirement(source, home, target)
        if current != plan:
            raise ValueError('stale_scope_retirement: recorded ownership changed')
        result = _detach_platforms_locked(source, home, target, current['clients'], preserve_neighbors=True)
        return current | result | {'applied': True}
