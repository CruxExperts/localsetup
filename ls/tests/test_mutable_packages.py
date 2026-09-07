import os
import shutil

import pytest

from ls.core.mutable_packages import MutablePackageError, capture_baselines, package_fingerprint, require_unchanged


def fixture(tmp_path):
    source = tmp_path / 'canonical/ls-fixture';source.mkdir(parents=True)
    (source / 'SKILL.md').write_text('skill')
    (source / 'references').mkdir()
    (source / 'references/data.txt').write_text('resource')
    adapter = tmp_path / 'native';adapter.mkdir()
    shutil.copytree(source, adapter / source.name)
    return source, adapter


def test_copy_baseline_is_independent_of_canonical_updates_and_neighbors(tmp_path):
    source, adapter = fixture(tmp_path)
    baseline = capture_baselines(adapter, ['ls-fixture'])
    assert package_fingerprint(source) == baseline['ls-fixture']
    (source / 'SKILL.md').write_text('new upstream version')
    (adapter / 'custom').mkdir()
    require_unchanged(adapter, baseline)
    assert (adapter / 'ls-fixture/SKILL.md').read_text() == 'skill'


@pytest.mark.parametrize('change', ['edit', 'delete-file', 'delete-package', 'add-file', 'add-empty-dir', 'mode', 'metadata'])
def test_local_mutations_require_preservation_before_replacement_or_removal(tmp_path, change):
    source, adapter = fixture(tmp_path)
    baseline = capture_baselines(adapter, ['ls-fixture']);package = adapter / 'ls-fixture'
    if change == 'edit':(package / 'SKILL.md').write_text('learned change')
    elif change == 'delete-file':(package / 'references/data.txt').unlink()
    elif change == 'delete-package':shutil.rmtree(package)
    elif change == 'add-file':(package / 'learned.txt').write_text('learned')
    elif change == 'add-empty-dir':(package / 'empty').mkdir()
    elif change == 'mode':(package / 'SKILL.md').chmod((package / 'SKILL.md').stat().st_mode ^ 0o100)
    else:(package / '.localsetup-managed.json').write_text('{}')
    with pytest.raises(MutablePackageError):require_unchanged(adapter, baseline)
    assert (source / 'SKILL.md').read_text() == 'skill'


@pytest.mark.parametrize('kind', ['file-link', 'dir-link', 'hardlink', 'fifo', 'root-link'])
def test_copies_cannot_reconnect_to_canonical_content(tmp_path, kind):
    source, adapter = fixture(tmp_path);package = adapter / 'ls-fixture'
    if kind == 'file-link':(package / 'link').symlink_to(source / 'SKILL.md')
    elif kind == 'dir-link':(package / 'link').symlink_to(source, target_is_directory=True)
    elif kind == 'hardlink':os.link(source / 'SKILL.md', package / 'link')
    elif kind == 'fifo':os.mkfifo(package / 'pipe')
    else:
        shutil.rmtree(package);package.symlink_to(source, target_is_directory=True)
    with pytest.raises(MutablePackageError):capture_baselines(adapter, ['ls-fixture'])


@pytest.mark.parametrize('baseline', [None, [], {'../escape': '0'*64}, {'ls-fixture': 'invalid'}, {'ls-fixture': None}])
def test_invalid_receipts_fail_closed(tmp_path, baseline):
    _, adapter = fixture(tmp_path)
    with pytest.raises(MutablePackageError):require_unchanged(adapter, baseline)


def test_inflight_file_change_is_detected(tmp_path, monkeypatch):
    _, adapter = fixture(tmp_path);original = os.read;changed = False
    def mutate(fd, count):
        nonlocal changed
        result = original(fd, count)
        if result and not changed:
            changed = True
            (adapter / 'ls-fixture/SKILL.md').write_text('changed during scan')
        return result
    monkeypatch.setattr(os, 'read', mutate)
    with pytest.raises(MutablePackageError, match='changed during inspection'):
        capture_baselines(adapter, ['ls-fixture'])


@pytest.mark.parametrize('overflow_pass', [1, 2])
def test_directory_enumeration_stops_before_exhausting_large_iterator(tmp_path, monkeypatch, overflow_pass):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from ls.core import mutable_packages as module
    root = tmp_path / 'package';root.mkdir()
    monkeypatch.setattr(module, 'MAX_ENTRIES', 4)
    original = os.scandir;calls = seen = 0
    @contextmanager
    def scan(fd):
        nonlocal calls, seen
        calls += 1
        if calls != overflow_pass:
            with original(fd) as entries:yield entries
        else:
            def oversized():
                nonlocal seen
                for number in range(1000):
                    seen += 1
                    yield SimpleNamespace(name=str(number))
            yield oversized()
    monkeypatch.setattr(os, 'scandir', scan)
    with pytest.raises(MutablePackageError, match='entry limit'):package_fingerprint(root)
    assert seen == 5
