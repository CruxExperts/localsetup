"""Plan repository-owner removal while preserving personal shared exposure."""
from .models import PlanAction
from .repository_overlap import expected_overlap


def shared_detach_actions(source, home, target_root, targets, recorded, global_root, mode):
    result = {}
    for target in targets:
        path = target['repo_path']
        action = PlanAction('attach_repo_path', path, {
            'packages': [], 'global_root': str(global_root),
            'mode': recorded.get(str(path), {}).get('mode', mode),
        })
        expected = expected_overlap(source, home, target_root, action)
        if expected is not None:result[str(path)] = (action, expected)
    return result
