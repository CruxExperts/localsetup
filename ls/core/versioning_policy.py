"""Committed repository release policy, anchor validation and sequential planning."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .git_subprocess import run_git
from . import versioning_sequence as sequence
from .versioning_constants import VERSION_SYNC_PREFIX, BREAKING_SUBJECT_RE, BREAKING_CHANGE_RE
from .versioning_models import SemVer

POLICY_PATH = '.localsetup-release.json'
POLICY = 'sequential-logical-slices'
DIGEST = re.compile(r'[0-9a-f]{40}\Z')
MAX_BYTES = 64 * 1024


def _git(root, arguments, *, check=True):
    return run_git(root, arguments, text=True, capture_output=True, check=check)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate release policy key')
        result[key] = value
    return result


def _constant(value):
    raise ValueError('Nonfinite release policy value')


def validate(value: object) -> dict:
    if (not isinstance(value, dict) or set(value) != {'schema_version', 'policy', 'anchor', 'overrides'}
            or type(value['schema_version']) is not int or value['schema_version'] != 1
            or value['policy'] != POLICY):
        raise ValueError('Invalid release policy envelope')
    anchor = value['anchor']
    if not isinstance(anchor, dict) or set(anchor) != {'commit', 'version', 'tag'}:
        raise ValueError('Invalid release policy anchor')
    if not isinstance(anchor['commit'], str) or not DIGEST.fullmatch(anchor['commit']):
        raise ValueError('Release anchor requires a full commit SHA')
    version = anchor['version']
    if not isinstance(version, str) or len(version) > 64 or str(SemVer.parse(version)) != version:
        raise ValueError('Release anchor requires a canonical version')
    if anchor['tag'] != 'v' + version:
        raise ValueError('Release anchor tag must match its version')
    overrides = value['overrides']
    if not isinstance(overrides, list) or len(overrides) > 256:
        raise ValueError('Release policy allows at most 256 exact overrides')
    seen = set()
    for row in overrides:
        if not isinstance(row, dict) or set(row) != {'commit', 'slice', 'classification'}:
            raise ValueError('Invalid release override fields')
        if not isinstance(row['commit'], str) or not DIGEST.fullmatch(row['commit']) or row['commit'] in seen:
            raise ValueError('Release overrides require distinct full commit SHAs')
        if not isinstance(row['slice'], str) or not sequence.SLICE.fullmatch(row['slice']):
            raise ValueError('Release override requires a bounded slice identity')
        if not isinstance(row['classification'], str) or row['classification'] not in sequence.RANK:
            raise ValueError('Release override requires a release classification')
        seen.add(row['commit'])
    return value


def load(root: Path, head: str) -> dict | None:
    """Read only the selected commit's bounded regular blob, never loose policy."""
    entry = _git(root, ['ls-tree', '-z', head, '--', POLICY_PATH]).stdout
    if not entry:
        return None
    fields, path = entry.rstrip('\0').split('\t', 1)
    mode, kind, digest = fields.split()
    if mode not in {'100644', '100755'} or kind != 'blob' or path != POLICY_PATH:
        raise ValueError('Release policy must be a regular committed Git blob')
    size = int(_git(root, ['cat-file', '-s', digest]).stdout)
    if not 0 < size <= MAX_BYTES:
        raise ValueError('Release policy exceeds the 64 KiB limit')
    raw = run_git(root, ['cat-file', 'blob', digest], text=False, capture_output=True, check=True).stdout
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=_object, parse_constant=_constant)
    except (ValueError, RecursionError) as exc:
        raise ValueError('Invalid committed release policy JSON') from exc
    return validate(value)


def validate_anchor(root: Path, configuration: dict, head: str) -> None:
    anchor = configuration['anchor']
    sha = anchor['commit']
    kind = _git(root, ['cat-file', '-t', sha], check=False)
    if kind.returncode or kind.stdout.strip() != 'commit':
        raise ValueError('Release anchor commit is unavailable')
    if _git(root, ['merge-base', '--is-ancestor', sha, head], check=False).returncode:
        raise ValueError('Release anchor must be an ancestor of the planned head')
    if str(sequence.committed_version(root, sha)) != anchor['version']:
        raise ValueError('Release anchor committed VERSION differs from policy')


def validated_overrides(configuration, commits, exclusions):
    overrides = {} if configuration is None else {row['commit']: row for row in configuration['overrides']}
    known = {commit.sha: commit for commit in commits}
    for sha, row in overrides.items():
        if sha not in known or sha in exclusions or sequence.REVERT.search(known[sha].body):
            raise ValueError(f'Release override {sha} must name an unpublished source commit')
        commit = known[sha]
        if (BREAKING_SUBJECT_RE.match(commit.subject) or BREAKING_CHANGE_RE.search(commit.body)) and row['classification'] != 'major':
            raise ValueError(f'Release override {sha} cannot downgrade a breaking change')
    return overrides


def plan(root: Path, *, base=None, head=None, ref=None, policy=None) -> dict:
    from . import versioning as api
    selected_head = api.resolve_head(root, head)
    configuration = load(root, selected_head)
    selected_policy = configuration['policy'] if configuration is not None else policy or 'patch-default'
    if configuration is not None and policy is not None and policy != selected_policy:
        raise ValueError('Explicit release policy conflicts with the committed repository contract')
    if selected_policy == 'patch-default':
        return api._plan_version_legacy(root, base=base, head=selected_head, ref=ref)
    if selected_policy != POLICY:
        raise ValueError(f'Unknown release policy: {selected_policy}')
    if configuration is not None:
        validate_anchor(root, configuration, selected_head)
    return plan_sequential(root, base=base, head=selected_head, ref=ref, configuration=configuration)


def guard_target(root: Path, target: str) -> None:
    """Protect explicit mutation targets under a committed repository contract."""
    from . import versioning as api
    selected_head = api._rev_parse(root, "HEAD")
    if selected_head is None or load(root, selected_head) is None:
        return
    result = plan(root)
    if not result['repairable']:
        raise ValueError('Release history requires reconciliation before version mutation')
    if target != result['target_version']:
        raise ValueError('Requested version differs from the committed release policy target')


def plan_sequential(repo_root: Path, *, base: str | None = None, head: str | None = None, ref: str | None = None, configuration: dict | None = None) -> dict:
    from . import versioning as api
    resolved_head = api.resolve_head(repo_root, head)
    base_payload = api.resolve_base_with_metadata(repo_root, base, resolved_head)
    comparison_base = str(base_payload["base"])
    resolved_base = configuration['anchor']['commit'] if configuration is not None else comparison_base
    base_resolution = base_payload['base_resolution']
    if api._run_git(repo_root, ["merge-base", "--is-ancestor", resolved_base, resolved_head], check=False).returncode:
        raise ValueError("Release base must be an ancestor of the selected head")
    commits = api.list_integrated_commits(repo_root, resolved_base, resolved_head)
    exclusions = {commit.sha: reason for commit in commits if (reason := sequence.exclusion(repo_root, commit))}
    known = {commit.sha for commit in commits}
    for commit in commits:
        for reverted in sequence.REVERT.findall(commit.body):
            if reverted not in known and (api._rev_parse(repo_root, reverted) is None or
                    api._run_git(repo_root, ["merge-base", "--is-ancestor", reverted, resolved_base], check=False).returncode):
                raise ValueError(f"Revert {commit.sha} does not name a source in this range or published base ancestry")
    overrides = validated_overrides(configuration, commits, exclusions)
    net_commits, canceled = sequence.cancel_reverts(commits, set(exclusions), repo_root=repo_root, overrides=overrides)
    release_type_required = [{"sha": item.sha, "subject": item.subject,
                              "message": "Breaking release markers require an explicit Release-Type: major compatibility decision."}
                             for item in net_commits if item.sha not in exclusions and sequence.requires_major_decision(item) and overrides.get(item.sha, {}).get('classification') != 'major']
    classifications = {commit.sha: "none" if commit.sha in exclusions else api._source_classification(commit) for commit in commits}
    classifications.update({sha: row['classification'] for sha, row in overrides.items()})
    bump = api.max_bump(classifications[commit.sha] for commit in net_commits)
    base_version = sequence.committed_version(repo_root, resolved_base)
    target, logical_slices = sequence.fold(net_commits, classifications, base_version, overrides=overrides)
    current = sequence.committed_version(repo_root, resolved_head)
    worktree = api.read_version(repo_root)
    sync_commits = [commit for commit in commits if commit.subject.startswith(VERSION_SYNC_PREFIX)]
    version_sync_present = bool(sync_commits)
    sync_checks = []
    for commit in commits:
        if commit not in sync_commits:
            continue
        ancestors = [item for item in api.list_integrated_commits(repo_root, resolved_base, commit.sha) if item.sha != commit.sha]
        prefix, _ = sequence.cancel_reverts(ancestors, set(exclusions), repo_root=repo_root, overrides=overrides)
        prefix_types = {item.sha: classifications[item.sha] for item in prefix}
        prefix_target, _ = sequence.fold(prefix, prefix_types, base_version, overrides=overrides)
        sync_checks.append({"sha": commit.sha, "expected_version": str(prefix_target),
                            "recorded_version": str(api.version_from_sync_commit(commit.subject)),
                            "committed_version": str(sequence.committed_version(repo_root, commit.sha)),
                            "ok": (api.version_from_sync_commit(commit.subject) == prefix_target
                                   and sequence.committed_version(repo_root, commit.sha) == prefix_target)})
    version_sync_matches_target = all(check["ok"] for check in sync_checks)
    latest_sync_matches_target = not sync_commits or api.version_from_sync_commit(sync_commits[-1].subject) == target
    head_version_matches_target = current == target
    head_version_required = version_sync_present or bump != "none"
    ok = (
        (not head_version_required or head_version_matches_target)
        and version_sync_matches_target
        and latest_sync_matches_target
        and not release_type_required
    )
    return {
        "ok": ok,
        "policy": POLICY,
        "repairable": version_sync_matches_target and not release_type_required,
        "comparison_base": comparison_base,
        "comparison_base_resolution": base_resolution,
        "anchor": None if configuration is None else configuration['anchor'],
        "release_overrides": list(overrides.values()),
        "logical_slices": logical_slices,
        "excluded_commits": [{"sha": sha, "reason": reason} for sha, reason in exclusions.items()],
        "version_sync_checks": sync_checks,
        "latest_sync_matches_target": latest_sync_matches_target,
        "ref": ref,
        "base": resolved_base,
        "head": resolved_head,
        "base_resolution": (base_resolution if configuration is None else api._base_result(
            status="resolved", strategy="committed_release_anchor", ref=configuration["anchor"]["tag"],
            sha=resolved_base, attempts=[])),
        "base_version": str(base_version),
        "current_version": str(current),
        "worktree_version": str(worktree),
        "target_version": str(target),
        "major_minor": target.major_minor,
        "bump": bump,
        "release_type_required": bool(release_type_required),
        "release_type_required_commits": release_type_required,
        "version_sync_present": version_sync_present,
        "version_sync_matches_target": version_sync_matches_target,
        "commit_count": len(commits),
        "net_commit_count": len(net_commits),
        "canceled_reverts": canceled,
        "commits": [
            {
                "sha": commit.sha,
                "subject": commit.subject,
                "bump": classifications[commit.sha],
                "raw_bump": api.classify_commit(commit.subject, commit.body),
                "release_type_required": sequence.requires_major_decision(commit) and overrides.get(commit.sha, {}).get('classification') != 'major',
                "files": api.changed_files(repo_root, commit.sha),
            }
            for commit in net_commits
        ],
    }

