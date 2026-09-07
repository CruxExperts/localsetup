"""Distinguish retired repository exposure from current personal ownership."""
from .manifests import load_pack_config
from .models import PlanAction
from .paths import expand_user_path
from .registry import load_registry
from .repository_overlap import expected_overlap


def retained_historical_action(source, home, target, path, global_root):
    registry = load_registry(expand_user_path(load_pack_config(source).global_registry, home))
    owners = registry.get('personal_owners', {})
    if not isinstance(owners, dict):raise ValueError('Invalid personal ownership registry')
    rows = []
    for row in owners.values():
        if not isinstance(row, dict) or not isinstance(row.get('paths'), list):
            raise ValueError('Invalid personal owner paths')
        if str(path) in row['paths']:rows.append(row)
    if not rows:return None
    action = PlanAction('attach_repo_path', path, {'packages': [], 'global_root': str(global_root),
                                                 'mode': rows[0].get('mode', 'symlink')})
    expected = expected_overlap(source, home, target, action)
    return action, expected
