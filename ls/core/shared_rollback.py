"""Rollback a repository sharing adapters with independent personal owners."""
import os
import uuid
from pathlib import Path

from .adapter_markers import ADAPTER_MARKER_JSON, adapter_marker_packages, adapter_marker_state
from .adapters import _child_is_managed_adapter_package, adapter_path_state, remove_managed_adapter_entries, legacy_global_roots
from .apply_journal import record_node_state, record_file_state, remove_path, journal_path, write_journal, restore_failed_mutations, cleanup_backups
from .manifests import load_pack_config
from .package_cleanup import is_package_backup_artifact
from .paths import expand_user_path
from .provenance import is_managed_package
from .registry import load_registry, package_has_other_refs, remove_target
from .repository_overlap import write_overlap
from .shared_detach import shared_detach_actions


def _snapshot_adapter(path, global_root, journal, receipt):
    if path.is_symlink():
        record_file_state(journal, receipt, path, os.replace)
    elif path.is_dir():
        mode = adapter_marker_state(path)['mode']
        candidates = adapter_marker_packages(path) or set(adapter_path_state(path, global_root).get('managed_visible_packages', []))
        for name in sorted(candidates):
            entry = path / name
            if _child_is_managed_adapter_package(entry, global_root, mode, None):
                record_node_state(journal, receipt, entry, os.replace)
        for name in (ADAPTER_MARKER_JSON, '.localsetup-portable'):
            entry = path / name
            if entry.is_file() and not entry.is_symlink():record_file_state(journal, receipt, entry, os.replace)


def shared_rollback(source, home, target, lock, lock_path, legacy_path):
    pack = load_pack_config(source)
    global_root = expand_user_path(pack.global_root, home)
    registry_path = expand_user_path(pack.global_registry, home)
    registry = load_registry(registry_path)
    paths = [Path(p) if Path(p).is_absolute() else target / p for p in lock.get('adapter_state', [])]
    recorded = {str(row['path']): row for row in lock.get('adapter_targets', [])}
    shared = shared_detach_actions(source, home, target, [{'repo_path': p} for p in paths], recorded,
                                   global_root, lock.get('attach_mode', 'symlink'))
    if not shared:return None
    candidates = [p for p in global_root.iterdir() if not p.name.startswith('.localsetup-')
                  and not is_package_backup_artifact(p) and is_managed_package(p)
                  and not package_has_other_refs(registry, p.name, target_root=target)] if global_root.exists() else []
    from .rollback import _require_under_global_root
    for path in candidates:_require_under_global_root(path, global_root)
    receipt = journal_path(target, 'rollback-' + uuid.uuid4().hex)
    journal = {'version': 1, 'operation': 'rollback', 'status': 'started', 'touched': []}
    removed = [];warnings = []
    try:
        for path in dict.fromkeys([lock_path, legacy_path, registry_path]):
            record_file_state(journal, receipt, path, os.replace)
        for path in paths:
            if str(path) in shared:
                action, expected = shared[str(path)];old = adapter_marker_packages(path) or set()
                write_overlap(source, home, target, action, journal, receipt)
                removed.extend(str(path / name) for name in sorted(old - set(expected)))
            else:
                _snapshot_adapter(path, global_root, journal, receipt)
                removed.extend(remove_managed_adapter_entries(path, global_root, known_global_roots=legacy_global_roots(home), preserve_directory=True))
        for path in candidates:
            record_node_state(journal, receipt, path, os.replace)
            remove_path(path);removed.append(str(path))
        remove_target(registry_path, target_root=target)
        for path in dict.fromkeys([lock_path, legacy_path]):
            if path.exists() or path.is_symlink():path.unlink();removed.append(str(path))
        journal['status'] = 'committed';write_journal(receipt, journal)
    except Exception:
        journal['status'] = 'failed'
        try:restore_failed_mutations(journal, os.replace)
        except Exception as exc:journal['rollback_error'] = str(exc)
        write_journal(receipt, journal)
        raise
    try:cleanup_backups(journal)
    except OSError as exc:warnings.append(f'rollback committed; backup cleanup failed: {exc}')
    return {'removed': removed, 'warnings': warnings, 'journal': str(receipt)}
