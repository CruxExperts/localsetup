"""Keep default OpenClaw personal adapters separate from native home overrides."""
import os
from pathlib import Path


def openclaw_personal_root(home: Path) -> dict:
    result = {'rule': 'openclaw_personal_root', 'scope': 'static-discovery',
              'path': str(home / '.agents/skills'), 'host_verified': False}
    override = os.environ.get('OPENCLAW_STATE_DIR', '').strip()
    effective_home = os.environ.get('OPENCLAW_HOME', '').strip()
    try:
        native_home = Path(effective_home) if effective_home else home
        default = not override or (
            native_home.is_absolute() and Path(override).is_absolute() and
            Path(override).resolve() == (native_home / '.openclaw').resolve())
    except (OSError, ValueError, RuntimeError):
        default = False
    return result | {'ok': default, 'status': 'default' if default else 'unqualified',
        'reason': ('Default-state common discovery predicate satisfied; selected agent, OS home and host loading remain unqualified' if default else
                   'OpenClaw state override is outside the statically supported default profile; preserve recorded roots and qualify the selected native profile before personal writes')}


def openclaw_prerequisite_blockers(source, actions, home, target):
    from .amp_ownership import records, affected_actions
    try:
        recorded, library = records(source, home)
        extra, _ = affected_actions(actions, recorded, library, client_id='openclaw')
        from .registry import load_registry
        from .manifests import load_pack_config
        from .paths import expand_user_path
        registry = load_registry(expand_user_path(load_pack_config(source).global_registry, home))
        personal_paths = {Path(path) for row in registry.get('personal_owners', {}).values()
                          if row['owner']['client'] == 'openclaw' for path in row['paths']}
        selected = any(a.path == home / '.agents/skills' and
                       any(o.get('client') == 'openclaw' and o.get('scope') == 'personal'
                           for o in a.details.get('owners', [])) for a in actions)
        selected = selected or any(a.path in personal_paths for a in extra)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError):
        return [{'path': str(target), 'status_code': 'openclaw_ownership_unverified',
                 'reason': 'Affected OpenClaw ownership cannot be established from registry metadata'}]
    if not selected:return []
    result = openclaw_personal_root(home)
    return [] if result['ok'] else [{'path': result['path'], 'status_code': 'openclaw_personal_root', 'reason': result['reason']}]
