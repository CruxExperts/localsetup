"""Plan package refreshes from recorded personal ownership, without reselection."""
import hashlib
import json
from pathlib import Path

from .installation_ownership import InstallationOwner
from .manifests import load_pack_config
from .models import PlanAction
from .paths import expand_user_path
from .personal_inventory import personal_inventory
from .personal_registry import owner_key
from .plan import build_install_plan
from .skills import load_skill_catalog


def build_recorded_personal_plan(source: Path, home: Path, target: Path):
    lock_path = target / '.localsetup/lock.json'
    if not lock_path.exists():
        lock_path = target / 'localsetup.lock.json'
    lock_bytes = lock_path.read_bytes()
    lock = json.loads(lock_bytes)
    if not isinstance(lock, dict) or lock.get('skill_scope') != 'personal':
        raise ValueError('A recorded personal-only installation is required')
    clients = lock.get('platforms')
    if not isinstance(clients, list) or any(not isinstance(c, str) or not c for c in clients):
        raise ValueError('Invalid recorded personal client selection')
    registry_path = expand_user_path(load_pack_config(source).global_registry, home)
    snapshots = {str(lock_path): hashlib.sha256(lock_bytes).hexdigest(),
                 str(registry_path): hashlib.sha256(registry_path.read_bytes()).hexdigest()}
    inventory = personal_inventory(source, home, clients, expected=lock.get('personal_adapter_targets', []))
    if not inventory['ok']:
        raise ValueError('Repair personal adapters before updating: ' + '; '.join(inventory['issues']))
    owners = inventory['owners']
    if {row['owner']['client'] for row in owners} != set(clients):
        raise ValueError('Recorded personal clients are missing ownership records')
    requested = {name for row in owners for name in row['packages']}
    baseline = lock.get('global_baseline_packages', [])
    if not isinstance(baseline, list) or any(not isinstance(n, str) for n in baseline):
        raise ValueError('Invalid recorded global package baseline')
    packages = requested | set(baseline)
    skills = {skill.name for skill in load_skill_catalog(source)}
    workflows = {p.name for p in (source / 'ls/workflows').iterdir() if p.is_dir()}
    if packages - skills - workflows:
        raise ValueError('Recorded packages are unavailable in the update source')
    selected_skills = sorted(packages & skills)
    selected_workflows = sorted(packages & workflows)
    plan = build_install_plan(source, home, global_preset='custom', global_skills=selected_skills,
                              global_workflows=selected_workflows, platform_ids=[], target_root=target,
                              skill_scope='personal')
    for action in plan.actions:
        if action.kind == 'install_skills':action.details['skills'] = selected_skills
        if action.kind == 'install_workflows':action.details['workflows'] = selected_workflows
    metadata = plan.rollback_metadata
    for key, value in lock.items():
        if key.startswith('global_baseline_'):metadata[key] = value
    metadata["aliases"] = {k: v for k, v in metadata["aliases"].items() if v in selected_skills}
    metadata.update(attach_mode=lock.get("attach_mode", "symlink"), platforms=clients, global_only=not clients, skills=selected_skills,
                    workflows=selected_workflows, packages=sorted(packages),
                    repo_packages=sorted(requested), repo_skills=sorted(requested & skills),
                    repo_workflows=sorted(requested & workflows), adapter_packages=sorted(requested),
                    recorded_state_hashes=snapshots)
    actions = {}
    for row in owners:
        for path in row['paths']:
            action = actions.setdefault(path, PlanAction('attach_personal_path', Path(path), {
                'platforms': [], 'owners': [], 'owner_packages': {}, 'packages': [],
                'mode': row['mode'], 'global_root': str(expand_user_path(load_pack_config(source).global_root, home))}))
            if action.details['mode'] != row['mode']:
                raise ValueError('Recorded owners disagree on the shared adapter mode')
            action.details['platforms'].append(row['owner']['client'])
            action.details['owners'].append(row['owner'])
            action.details['owner_packages'][owner_key(InstallationOwner(**row['owner']))] = row['packages']
            action.details['packages'] = sorted(set(action.details['packages']) | set(row['packages']))
    plan.actions.extend(actions[path] for path in sorted(actions))
    agents = lock.get('codex_agents', [])
    if agents:
        if agents != ['guardian_subagent']:raise ValueError('Unsupported recorded Codex agent selection')
        plan.actions.append(PlanAction('install_codex_agents', home / '.codex/agents', {'agents': agents}))
        metadata['codex_agents'] = agents
    return plan
