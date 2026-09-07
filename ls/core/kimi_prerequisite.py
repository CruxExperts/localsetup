"""Read Kimi's generic personal-root selection without native initialization."""
from pathlib import Path
import stat


def kimi_personal_root(home: Path) -> dict:
    common = home / '.agents/skills'
    preferred = home / '.config/agents/skills'
    result = {'rule': 'kimi_personal_root_visible', 'scope': 'static-discovery',
              'path': str(common), 'preferred_path': str(preferred), 'host_verified': False}
    try:
        try:directory = stat.S_ISDIR(preferred.stat().st_mode)
        except (FileNotFoundError, NotADirectoryError):directory = False
        masked = directory and preferred.resolve() != common.resolve()
    except (OSError, RuntimeError):
        return result | {'ok': False, 'status': 'unknown', 'reason': 'Kimi generic personal roots require path review'}
    if masked:
        return result | {'ok': False, 'status': 'masked',
            'reason': 'Kimi selects ~/.config/agents/skills before ~/.agents/skills, even when empty; preserve both roots and review native discovery before personal installation'}
    return result | {'ok': True, 'status': 'unmasked',
                     'reason': 'No distinct higher-priority generic personal directory masks the common root; host loading remains unverified'}


def kimi_prerequisite_blockers(source, actions, home, target):
    from .amp_ownership import records, affected_actions
    try:
        recorded, library = records(source, home)
        extra, _ = affected_actions(actions, recorded, library, client_id='kimi-cli')
        selected = any(a.path == home / '.agents/skills' and
                       ('kimi-cli' in a.details.get('platforms', []) or
                        any(o.get('client') == 'kimi-cli' for o in a.details.get('owners', [])))
                       for a in [*actions, *extra])
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError):
        return [{'path': str(target), 'status_code': 'kimi_ownership_unverified',
                 'reason': 'Affected Kimi ownership cannot be established from registry metadata'}]
    if not selected:return []
    result = kimi_personal_root(home)
    return [] if result['ok'] else [{'path': result['path'], 'status_code': 'kimi_personal_mask', 'reason': result['reason']}]
