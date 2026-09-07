"""Nonblocking source-shape evidence, separate from filesystem verification."""
import os
from pathlib import Path

SOURCE_COMMIT = 'e0ef9096391ebffba8560875665a2d7249ac6dc5'


def kilo_loading_assessment(target: Path, adapters: list[dict], personal: dict) -> list[dict]:
    """Assess project source containment without reading or executing skill text."""
    results = []
    for adapter in adapters:
        clients = set(adapter.get('platforms', [])) | {adapter.get('platform')}
        if 'kilo' not in clients:continue
        names = adapter.get('expected_packages', [])
        status = 'source-contained' if names else 'unqualified'
        try:
            root = target.resolve(strict=True)
            for name in names:
                from .adapter_markers import is_safe_adapter_package_name
                if not isinstance(name, str) or not is_safe_adapter_package_name(name):
                    status = 'unqualified';break
                source = (Path(adapter['repo_path']) / name / 'SKILL.md').resolve(strict=True)
                if not source.is_relative_to(root):
                    status = 'unsupported-project-source';break
        except (OSError, ValueError, RuntimeError, TypeError):
            status = 'unqualified'
        results.append({'client': 'kilo', 'scope': 'repo', 'path': adapter['repo_path'],
                        'status': status, 'host_verified': False, 'source_commit': SOURCE_COMMIT,
                        'policy_basis': 'ordinary-untrusted-project-root',
                        'reason': ('Under the Kilo 7.5.15 ordinary project-root policy, external skill sources cannot load. Effective native configuration remains unqualified; review a portable-mode plan without raising trust.'
                                   if status == 'unsupported-project-source' else
                                   'Source containment only; native configuration, activation and resources remain unqualified.')})
    if any(row.get('owner', {}).get('client') == 'kilo' for row in personal.get('owners', [])):
        results.append({'client': 'kilo', 'scope': 'personal', 'status': 'unqualified',
                        'host_verified': False, 'source_commit': SOURCE_COMMIT,
                        'reason': 'Personal skill trust depends on effective home, active project and resolved targets; filesystem installation is not native qualification.'})
    overrides = [name for name in ('KILO_DISABLE_EXTERNAL_SKILLS', 'KILO_TEST_HOME', 'KILO_CONFIG_DIR',
                                  'KILO_CONFIG', 'KILO_CONFIG_CONTENT', 'KILO_DISABLE_PROJECT_CONFIG')
                 if name in os.environ]
    if results and overrides:
        results.append({'client': 'kilo', 'scope': 'configuration', 'status': 'unqualified',
                        'host_verified': False, 'source_commit': SOURCE_COMMIT,
                        'reason': 'Native environment overrides require effective-configuration qualification.',
                        'override_names': overrides})
    return results
