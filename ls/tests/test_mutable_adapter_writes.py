import json
from pathlib import Path

import pytest

from ls.core.adapter_markers import ADAPTER_MARKER_JSON
from ls.core.adapters import remove_managed_adapter_entries
from ls.core.apply import _write_scoped_adapter
from ls.core.apply_journal import restore_failed_mutations
from ls.core.models import PlanAction
from ls.core.mutable_adapters import check_existing
from ls.core.mutable_packages import MutablePackageError
from ls.core.personal_adapter import write_entries


def fixture(tmp_path):
    library = tmp_path / 'library';package = library / 'ls-fixture'
    package.mkdir(parents=True)
    (package / 'SKILL.md').write_text('original')
    (package / '.localsetup-managed.json').write_text('{}')
    return library, tmp_path / 'adapter'


def write(kind, tmp_path, library, adapter, *, mutable=False):
    if kind == 'repo':
        _write_scoped_adapter(adapter, library, ['ls-fixture'], mode='portable', mutable=mutable)
    else:
        action = PlanAction('attach_personal_path', adapter, {'global_root': str(library),
                           'mode': 'portable', 'mutable_copy': mutable})
        write_entries(tmp_path, action, ['ls-fixture'], {'touched': []}, tmp_path / 'journal.json')


@pytest.mark.parametrize('kind', ['repo', 'personal'])
def test_writer_records_baseline_and_preserves_opt_in_across_upstream_update(tmp_path, kind):
    library, adapter = fixture(tmp_path)
    write(kind, tmp_path, library, adapter, mutable=True)
    before = check_existing(adapter, required=True)
    (library / 'ls-fixture/SKILL.md').write_text('new upstream')
    write(kind, tmp_path, library, adapter)
    assert check_existing(adapter, required=True) != before
    assert (adapter / 'ls-fixture/SKILL.md').read_text() == 'new upstream'
    assert (adapter / 'ls-fixture/SKILL.md').stat().st_ino != (library / 'ls-fixture/SKILL.md').stat().st_ino


@pytest.mark.parametrize('kind', ['repo', 'personal'])
@pytest.mark.parametrize('change', ['edit', 'delete'])
def test_update_and_remove_refuse_copy_drift_without_losing_receipt(tmp_path, kind, change):
    library, adapter = fixture(tmp_path)
    write(kind, tmp_path, library, adapter, mutable=True)
    receipt = adapter / ADAPTER_MARKER_JSON;before = receipt.read_bytes()
    skill = adapter / 'ls-fixture/SKILL.md'
    if change == 'edit':skill.write_text('learned')
    else:skill.unlink()
    with pytest.raises(MutablePackageError):write(kind, tmp_path, library, adapter)
    with pytest.raises(MutablePackageError):remove_managed_adapter_entries(adapter, library)
    assert receipt.read_bytes() == before
    assert skill.read_text() == 'learned' if change == 'edit' else not skill.exists()
    assert (library / 'ls-fixture/SKILL.md').read_text() == 'original'


@pytest.mark.parametrize('kind', ['repo', 'personal'])
def test_unsafe_source_links_refused_before_adapter_creation(tmp_path, kind):
    library, adapter = fixture(tmp_path)
    (library / 'ls-fixture/resource').symlink_to(library / 'ls-fixture/SKILL.md')
    with pytest.raises(MutablePackageError):write(kind, tmp_path, library, adapter, mutable=True)
    assert not adapter.exists()


def test_missing_or_inconsistent_baseline_cannot_satisfy_recorded_owner(tmp_path):
    library, adapter = fixture(tmp_path)
    write('repo', tmp_path, library, adapter, mutable=True)
    marker = adapter / ADAPTER_MARKER_JSON;payload = json.loads(marker.read_text())
    del payload['mutable_packages'];marker.write_text(json.dumps(payload))
    with pytest.raises(MutablePackageError):check_existing(adapter, required=True)
    marker.unlink()
    with pytest.raises(MutablePackageError):check_existing(adapter, required=True)


def test_personal_failed_post_copy_validation_restores_packages_and_receipt(tmp_path, monkeypatch):
    from ls.core import mutable_adapters
    import os
    library, adapter = fixture(tmp_path)
    write('personal', tmp_path, library, adapter, mutable=True)
    marker = adapter / ADAPTER_MARKER_JSON;before = marker.read_bytes()
    (library / 'ls-fixture/SKILL.md').write_text('upstream')
    action = PlanAction('attach_personal_path', adapter, {'global_root': str(library), 'mode': 'portable'})
    journal = {'touched': []}
    def fail(*args):raise MutablePackageError('injected copy validation failure')
    monkeypatch.setattr(mutable_adapters, 'receipt_fields', fail)
    with pytest.raises(MutablePackageError):
        write_entries(tmp_path, action, ['ls-fixture'], journal, tmp_path / 'failure.json')
    restore_failed_mutations(journal, os.replace)
    assert marker.read_bytes() == before
    assert (adapter / 'ls-fixture/SKILL.md').read_text() == 'original'


def test_clean_remove_preserves_custom_neighbor(tmp_path):
    library, adapter = fixture(tmp_path)
    write('repo', tmp_path, library, adapter, mutable=True)
    (adapter / 'custom.txt').write_text('keep')
    remove_managed_adapter_entries(adapter, library)
    assert not (adapter / 'ls-fixture').exists()
    assert not (adapter / ADAPTER_MARKER_JSON).exists()
    assert (adapter / 'custom.txt').read_text() == 'keep'


@pytest.mark.parametrize('kind', ['repo', 'personal'])
def test_mutable_opt_in_refuses_symlink_adapter_before_touching_target(tmp_path, kind):
    library, adapter = fixture(tmp_path)
    outside = tmp_path / 'outside';outside.mkdir()
    (outside / 'keep.txt').write_text('keep')
    adapter.symlink_to(outside, target_is_directory=True)
    with pytest.raises((MutablePackageError, ValueError)):
        write(kind, tmp_path, library, adapter, mutable=True)
    assert sorted(p.name for p in outside.iterdir()) == ['keep.txt']
    assert adapter.is_symlink()
