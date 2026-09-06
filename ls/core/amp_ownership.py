"""Recorded ownership evidence for Amp shared projections and portable copies."""
from pathlib import Path

from .adapter_markers import ADAPTER_MARKER_JSON, is_safe_adapter_package_name
from .installation_ownership import InstallationOwner
from .lockfile import load_json
from .manifests import load_pack_config
from .models import PlanAction
from .paths import expand_user_path
from .personal_inventory import _links
from .provenance import is_managed_package, package_digest
from .registry import load_registry


def _mapping(value):
    if not isinstance(value, dict):raise ValueError('ownership container must be an object')
    return value


def _list(value):
    if not isinstance(value, list):raise ValueError('ownership entries must be an array')
    return value


def _packages(value):
    names = _list(value)
    if any(not isinstance(n, str) or not is_safe_adapter_package_name(n) for n in names):
        raise ValueError('invalid owned package names')
    return set(names)


def records(source, home):
    pack = load_pack_config(source)
    registry = load_registry(expand_user_path(pack.global_registry, home))
    result = []
    for row in _mapping(registry.get('personal_owners', {})).values():
        row = _mapping(row)
        owner = InstallationOwner(**_mapping(row['owner']))
        if owner.scope != 'personal' or owner.root != str(home.resolve()):raise ValueError('invalid personal ownership')
        for path in _list(row['paths']):
            if not isinstance(path, str) or not Path(path).is_absolute():raise ValueError('invalid owned path')
            Path(path).relative_to(home)
            result.append((Path(path), _packages(row['packages']), row.get('mode', 'symlink'), {owner.client}, home))
    for target, record in _mapping(registry.get('targets', {})).items():
        if not isinstance(target, str) or not Path(target).is_absolute():raise ValueError('invalid target root')
        for row in _list(_mapping(record).get('adapters', [])):
            row = _mapping(row)
            owners = [InstallationOwner(**_mapping(o)) for o in _list(row.get('owners', []))]
            clients = {o.client for o in owners if o.scope == 'repo' and o.root == target}
            if not clients:continue
            path = Path(row['path'])
            if not path.is_absolute():path = Path(target) / path
            result.append((path, _packages(row.get('packages', [])), row.get('mode', 'symlink'), clients, Path(target)))
    return result, expand_user_path(pack.global_root, home)


def affected_actions(actions, recorded, library):
    extra = [];targets = []
    changed = {name for a in actions if a.kind in {'install_skills', 'install_workflows'} and a.path == library
               for name in a.details.get('skills', a.details.get('workflows', []))}
    for path, packages, mode, clients, target in recorded:
        if 'amp-cli' not in clients:continue
        physical = [a for a in actions if a.path == path and a.kind in {'attach_repo_path', 'attach_personal_path', 'repair_repo_path'}]
        names = (packages & changed) | {n for a in physical for n in a.details.get('packages', [])}
        if not names:continue
        extra.append(PlanAction('repair_repo_path', path, {'platforms': ['amp-cli'], 'packages': sorted(names),
                     'global_root': str(library), 'mode': mode, '_amp_recorded_only': True}))
        targets.append(target)
    return extra, targets


def portable_counterpart(path, library_package, expected, recorded):
    if path.is_symlink() or not any(root == path.parent and path.name in packages and mode == 'portable'
                                   for root, packages, mode, clients, target in recorded):return False
    marker = path.parent / ADAPTER_MARKER_JSON
    if marker.is_symlink() or not marker.is_file():return False
    data = _mapping(load_json(marker))
    if (data.get('managed_by') != 'localsetup' or data.get('mode') != 'portable'
            or path.name not in _packages(data.get('packages', []))
            or Path(data.get('global_root', '')).resolve() != library_package.parent.resolve()):return False
    return (is_managed_package(path) and package_digest(path) == package_digest(expected)
            and _links(path) == _links(expected))
