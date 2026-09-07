"""Read Goose's static Skills configuration prerequisite without native loading."""
import os
import stat
import sys
from pathlib import Path

import yaml

SYSTEM_CONFIG = Path('/etc/goose/config.yaml')


def _mapping(node):
    if not isinstance(node, yaml.MappingNode):raise ValueError('expected mapping')
    result = {}
    for key, value in node.value:
        if not isinstance(key, yaml.ScalarNode) or key.tag != 'tag:yaml.org,2002:str' or key.value in result:
            raise ValueError('ambiguous mapping key')
        result[key.value] = value
    return result


def _string(node, value):
    return isinstance(node, yaml.ScalarNode) and node.tag == 'tag:yaml.org,2002:str' and node.value == value


def goose_skills_configuration(home: Path) -> dict:
    path = home / '.config/goose/config.yaml'
    result = {'rule': 'goose_skills_configured', 'scope': 'static-configuration',
              'path': str(path), 'ok': False, 'status': 'unknown', 'host_verified': False}
    def unknown(reason):return result | {'reason': reason}
    if sys.platform not in {'linux', 'darwin'}:
        return unknown('Static Goose configuration inspection is qualified only on Linux/WSL and macOS paths')
    if (os.environ.get('GOOSE_PATH_ROOT') or os.environ.get('GOOSE_ADDITIONAL_CONFIG_FILES')
            or 'EXTENSIONS' in os.environ or SYSTEM_CONFIG.exists() or SYSTEM_CONFIG.is_symlink()):
        return unknown('Goose configuration overrides or system layers require separate effective-state qualification')
    xdg = os.environ.get('XDG_CONFIG_HOME')
    if xdg and Path(xdg).expanduser().absolute() != home.absolute() / '.config':
        return unknown('Nondefault XDG configuration roots require separate Goose qualification')
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):raise ValueError('configuration is not a regular file')
            raw = os.read(fd, 262145)
        finally:os.close(fd)
        if len(raw) > 262144:raise ValueError('configuration exceeds supported size')
        text = raw.decode('utf-8')
        if any(isinstance(token, (yaml.AliasToken, yaml.AnchorToken)) for token in yaml.scan(text)):
            raise ValueError('aliased configuration requires native resolution')
        config = _mapping(yaml.compose(text));extensions = _mapping(config.get('extensions'))
        for key, node in extensions.items():
            if key != 'skills' and _string(_mapping(node).get('name'), 'skills'):
                raise ValueError('multiple Skills identities')
        entry = _mapping(extensions.get('skills'));enabled = entry.get('enabled')
        if not (_string(entry.get('type'), 'platform') and _string(entry.get('name'), 'skills')):
            raise ValueError('native Skills identity required')
        if isinstance(enabled, yaml.ScalarNode) and enabled.tag == 'tag:yaml.org,2002:bool' and enabled.value.lower() == 'false':
            return result | {'status': 'disabled', 'reason': 'Goose Skills is explicitly disabled; configuration is preserved'}
        if not (isinstance(enabled, yaml.ScalarNode) and enabled.tag == 'tag:yaml.org,2002:bool'
                and enabled.value.lower() == 'true' and _string(entry.get('type'), 'platform')
                and _string(entry.get('name'), 'skills')):
            raise ValueError('explicit enabled native Skills entry required')
        tools = entry.get('available_tools')
        if tools is not None and not (isinstance(tools, yaml.SequenceNode) and not tools.value):
            raise ValueError('tool restrictions require session qualification')
    except (OSError, ValueError, UnicodeError, yaml.YAMLError, RecursionError):
        return unknown('An explicit, unambiguous enabled native Goose Skills entry is required; inspect configuration without running migrations')
    return result | {'ok': True, 'status': 'configured',
                     'reason': 'Explicit native Skills configuration found; build and session availability remain unverified'}


def goose_prerequisite_blockers(source, actions, home, target):
    from .amp_ownership import records, affected_actions
    try:
        recorded, library = records(source, home)
        extra, _ = affected_actions(actions, recorded, library, client_id='goose-cli')
        selected = any('goose-cli' in a.details.get('platforms', []) for a in [*actions, *extra])
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError):
        return [{'path': str(target), 'status_code': 'goose_ownership_unverified',
                 'reason': 'Affected Goose ownership cannot be established from registry metadata'}]
    if not selected:return []
    result = goose_skills_configuration(home)
    return [] if result['ok'] else [{'path': result['path'], 'status_code': 'goose_skills_prerequisite', 'reason': result['reason']}]
