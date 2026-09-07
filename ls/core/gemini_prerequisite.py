"""Keep default Gemini personal adapters separate from native home overrides."""
import os
from pathlib import Path


def gemini_personal_root(home: Path) -> dict:
    result = {'rule': 'gemini_personal_root', 'scope': 'static-discovery',
              'path': str(home / '.agents/skills'), 'host_verified': False}
    override = os.environ.get('GEMINI_CLI_HOME')
    try:
        default = not override or (
            Path(override).is_absolute() and Path(override).resolve() == home.resolve())
    except (OSError, ValueError, RuntimeError):
        default = False
    return result | {'ok': default, 'status': 'default' if default else 'unqualified',
        'reason': ('Default Gemini personal path selected; host loading remains unverified' if default else
                   'GEMINI_CLI_HOME differs from the qualified default or is ambiguous; preserve both roots and qualify the native home before personal writes')}


def gemini_prerequisite_blockers(source, actions, home, target):
    from .amp_ownership import records, affected_actions
    try:
        recorded, library = records(source, home)
        extra, _ = affected_actions(actions, recorded, library, client_id='gemini-cli')
        from .registry import load_registry
        from .manifests import load_pack_config
        from .paths import expand_user_path
        registry = load_registry(expand_user_path(load_pack_config(source).global_registry, home))
        personal_paths = {Path(path) for row in registry.get('personal_owners', {}).values()
                          if row['owner']['client'] == 'gemini-cli' for path in row['paths']}
        selected = any(a.path == home / '.agents/skills' and
                       any(o.get('client') == 'gemini-cli' and o.get('scope') == 'personal'
                           for o in a.details.get('owners', [])) for a in actions)
        selected = selected or any(a.path in personal_paths for a in extra)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError):
        return [{'path': str(target), 'status_code': 'gemini_ownership_unverified',
                 'reason': 'Affected Gemini ownership cannot be established from registry metadata'}]
    if not selected:return []
    result = gemini_personal_root(home)
    return [] if result['ok'] else [{'path': result['path'], 'status_code': 'gemini_personal_root', 'reason': result['reason']}]
