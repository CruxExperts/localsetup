"""Nonblocking source-shape evidence, separate from filesystem verification."""
import os
from pathlib import Path

SOURCE_COMMIT = '3928bad9badfcb6c7d140530435e806fb8092190'


def openclaw_loading_assessment(target: Path, adapters: list[dict], personal: dict) -> list[dict]:
    """Assess project source containment without reading or executing skill text."""
    results = []
    for adapter in adapters:
        clients = set(adapter.get('platforms', [])) | {adapter.get('platform')}
        if 'openclaw' not in clients:continue
        names = adapter.get('expected_packages', [])
        status = 'source-contained' if names else 'unqualified'
        try:
            root = Path(adapter['repo_path']).resolve(strict=True)
            for name in names:
                from .adapter_markers import is_safe_adapter_package_name
                if not isinstance(name, str) or not is_safe_adapter_package_name(name):
                    status = 'unqualified';break
                source = (Path(adapter['repo_path']) / name / 'SKILL.md').resolve(strict=True)
                if not source.is_relative_to(root):
                    status = 'unsupported-project-source';break
        except (OSError, ValueError, RuntimeError, TypeError):
            status = 'unqualified'
        results.append({'client': 'openclaw', 'scope': 'repo', 'path': adapter['repo_path'],
                        'status': status, 'host_verified': False, 'source_commit': SOURCE_COMMIT,
                        'policy_basis': 'ordinary-configured-skill-root',
                        'reason': ('Under the OpenClaw 2026.9.2 ordinary configured-skill-root policy, external skill sources cannot load. Effective native configuration remains unqualified; review a portable plan for the resolved agent workspace without changing native allowances.'
                                   if status == 'unsupported-project-source' else
                                   'Source containment only; native configuration, activation and resources remain unqualified.')})
    if any(row.get('owner', {}).get('client') == 'openclaw' for row in personal.get('owners', [])):
        results.append({'client': 'openclaw', 'scope': 'personal', 'status': 'unqualified',
                        'host_verified': False, 'source_commit': SOURCE_COMMIT,
                        'reason': 'Personal common discovery requires the default-state profile and matching OS home; filesystem installation is not native qualification.'})
    overrides = [name for name in ('OPENCLAW_HOME', 'OPENCLAW_STATE_DIR', 'OPENCLAW_CONFIG_PATH')
                 if name in os.environ]
    if results and overrides:
        results.append({'client': 'openclaw', 'scope': 'configuration', 'status': 'unqualified',
                        'host_verified': False, 'source_commit': SOURCE_COMMIT,
                        'reason': 'Native profile, workspace association and effective configuration require qualification.',
                        'override_names': overrides})
    return results
