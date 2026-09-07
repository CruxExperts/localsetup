"""Conservative canonical-name checks, not an emulation of Droid sanitization."""
import os
import re
from pathlib import Path

import yaml

from .amp_preflight import _name


def canonical_name(metadata: Path) -> str:
    name = _name(metadata)
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name):
        raise ValueError('noncanonical identity requires native catalog review')
    return name


def packages(root: Path, budget: list[int], ancestors=()):
    if not root.exists() and not root.is_symlink():return
    if not root.is_dir():raise ValueError('skill root is not a readable directory')
    resolved = root.resolve(strict=True)
    if resolved in ancestors or len(ancestors) >= 32:raise ValueError('skill traversal cycle or depth limit')
    metadata = root / 'SKILL.md'
    if metadata.exists() or metadata.is_symlink():
        yield root, canonical_name(metadata)
        return
    with os.scandir(root) as entries:
        for entry in entries:
            budget[0] += 1
            if budget[0] > 4096:raise ValueError('skill traversal exceeds 4096 entries')
            if entry.is_dir():yield from packages(Path(entry.path), budget, (*ancestors, resolved))
            elif entry.is_symlink():raise ValueError('unresolved skill link')


def factory_skill_blockers(source, actions, home, target):
    from .amp_ownership import records, affected_actions
    def blocked(path):
        return {'path': str(path), 'status_code': 'factory_skill_identity_conflict',
                'reason': 'Factory skill identity is duplicated or cannot be qualified from canonical local metadata; preserve all origins and inspect the native effective catalog'}
    try:
        recorded, library = records(source, home)
        extra, _ = affected_actions(actions, recorded, library, client_id='factory-droid')
        selected = [a for a in [*actions, *extra] if 'factory-droid' in a.details.get('platforms', [])
                    and a.kind in {'attach_repo_path', 'attach_personal_path', 'repair_repo_path'}]
        scopes = {}
        for action in selected:
            base = action.path.parent.parent
            if action.path != base / '.agents/skills':raise ValueError('unknown Factory adapter path')
            desired = scopes.setdefault(base, {})
            for package in action.details.get('packages', []):
                installed = library / package
                installing = next((a for a in actions if a.kind in {'install_skills', 'install_workflows'}
                                   and a.path / package == installed), None)
                original = source / 'ls' / ('workflows' if installing and installing.kind == 'install_workflows' else 'skills') / package
                if not installing and (installed / 'SKILL.md').is_file():original = installed
                if not (original / 'SKILL.md').exists():continue
                name = canonical_name(original / 'SKILL.md');destination = action.path / package
                if name in desired and desired[name] != destination:raise ValueError('planned duplicate name')
                desired[name] = destination
        for base, desired in scopes.items():
            budget = [0]
            for relative in ('.agents/skills', '.agent/skills', '.factory/skills'):
                for path, name in packages(base / relative, budget):
                    if any(path in destination.parents for destination in desired.values()):return [blocked(path)]
                    if name in desired and path != desired[name]:return [blocked(path)]
        return []
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError, UnicodeError, yaml.YAMLError):
        return [blocked(target)]
