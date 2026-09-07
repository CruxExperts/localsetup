"""Keep default Claude personal adapters separate from native home overrides."""
import os
from pathlib import Path


def claude_personal_root(home: Path) -> dict:
    result = {'rule': 'claude_personal_root', 'scope': 'static-discovery',
              'path': str(home / '.claude/skills'), 'host_verified': False}
    override = os.environ.get('CLAUDE_CONFIG_DIR')
    try:
        default = override is None or (bool(override) and
            Path(override).is_absolute() and Path(override).resolve() == (home / '.claude').resolve())
    except (OSError, ValueError, RuntimeError):
        default = False
    return result | {'ok': default, 'status': 'default' if default else 'unqualified',
        'reason': ('Default Claude personal path selected; host loading remains unverified' if default else
                   'CLAUDE_CONFIG_DIR differs from the qualified default or is ambiguous; preserve both roots and qualify the native home before personal writes')}


def claude_prerequisite_blockers(source, actions, home, target):
    from .amp_ownership import records, affected_actions
    try:
        recorded, library = records(source, home)
        extra, _ = affected_actions(actions, recorded, library, client_id='claude-code')
        selected = any(a.path == home / '.claude/skills' and
                       ('claude-code' in a.details.get('platforms', []) or
                        any(o.get('client') == 'claude-code' for o in a.details.get('owners', [])))
                       for a in [*actions, *extra])
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError):
        return [{'path': str(target), 'status_code': 'claude_ownership_unverified',
                 'reason': 'Affected Claude ownership cannot be established from registry metadata'}]
    if not selected:return []
    result = claude_personal_root(home)
    return [] if result['ok'] else [{'path': result['path'], 'status_code': 'claude_personal_root', 'reason': result['reason']}]
