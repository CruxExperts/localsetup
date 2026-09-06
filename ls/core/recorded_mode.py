"""Apply explicit mode requests to recorded plans without package reselection."""
import json
from pathlib import Path

from .apply_preflight import preflight_install_plan


def requested_mode(args):
    mode = getattr(args, 'mode', None)
    if mode is None and getattr(args, 'config', None):
        mode = json.loads(Path(args.config).read_text(encoding='utf-8')).get('attach_mode')
    return mode


def set_recorded_mode(source, home, target, plan, mode):
    if mode is None:return
    if mode not in {'symlink', 'portable'}:raise ValueError('Invalid requested adapter mode')
    for action in plan.actions:
        if action.kind in {'attach_repo_path', 'attach_personal_path'}:
            action.details['mode'] = mode
    plan.rollback_metadata['attach_mode'] = mode
    report = preflight_install_plan(source, plan, home, target_root=target)
    if not report['ok']:
        raise ValueError('Recorded mode change is unsafe: ' + '; '.join(b['reason'] for b in report['blockers']))
