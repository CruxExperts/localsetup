"""Adapt recorded personal repair to the standard doctor result contract."""
from pathlib import Path

from .path_contract import paths_manifest_issues, paths_manifest_path
from .personal_repair import repair_personal
from .repair_common import _latest_version


def personal_repair_route(
    source: Path, home: Path, target: Path, lock: dict, *, clients: list[str] | None,
    apply: bool, mode: str, allowed: list[str], warnings: list[str], blockers: list[str],
) -> dict:
    scope = lock['skill_scope']
    selected = lock.get('platforms', []) if clients is None else clients
    if not isinstance(selected, list) or any(not isinstance(c, str) or not c for c in selected):
        blockers.append('invalid recorded personal client selection')
        selected = []
    if scope == 'both':
        blockers.append('Combined repository and personal repair is not yet qualified')
    personal = repair_personal(source, home, selected, apply=apply and not blockers)
    blockers = [*blockers, *personal['blockers']]
    resolver_issues = paths_manifest_issues(source, home)
    return {
        'repair_schema_version': 2, 'skill_scope': scope,
        'ok': not blockers and personal['ok'], 'applied': personal['applied'],
        'source_root': str(source), 'target_root': str(target),
        'latest_version': _latest_version(source), 'repair_mode': mode, 'allowed': allowed,
        'detected_shape': {'modern_lockfile': str(target / '.localsetup/lock.json')
                           if (target / '.localsetup/lock.json').exists() else None,
                           'legacy_lockfile': str(target / 'localsetup.lock.json')
                           if (target / 'localsetup.lock.json').exists() else None,
                           'adapter_paths': [], 'historical_adapter_paths': []},
        'resolver': {'ok': not resolver_issues, 'issues': resolver_issues,
                     'manifest': str(paths_manifest_path(home))},
        'inferred': {'platforms': selected, 'repo_packages': [], 'repo_skills': [],
                     'repo_workflows': [], 'personal_owners': personal['verification']['owners']},
        'actions': personal['actions'], 'decisions': [], 'backups': [],
        'verify': personal['verification'], 'personal': personal,
        'blockers': blockers, 'warnings': warnings,
        'next_actions': ['localsetup doctor repair --repair-mode safe-repair --yes']
                        if personal['actions'] and not apply and not blockers else [],
        'metrics': {'blocker_count': len(blockers), 'decision_count': 0,
                    'decision_kinds': [], 'repo_package_count': 0},
    }
