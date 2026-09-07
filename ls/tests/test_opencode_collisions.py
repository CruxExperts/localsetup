from pathlib import Path

import pytest

from ls.core.opencode_collisions import conflicting_sources, skill_sources


def skill(path, name='ls-context'):
    path.mkdir(parents=True)
    metadata = path / 'SKILL.md'
    metadata.write_text(f'---\nname: {name}\ndescription: fixture\n---\nbody\n')
    return metadata


def test_conflicts_include_nested_names_but_coalesce_exact_source_links(tmp_path):
    source = skill(tmp_path / 'source')
    common = tmp_path / 'common';common.mkdir()
    (common / 'ls-context').symlink_to(source.parent, target_is_directory=True)
    native = tmp_path / 'native'
    duplicate = skill(native / 'nested/duplicate')
    skill(native / 'unrelated', 'other')
    assert conflicting_sources([common, native, common], {'ls-context': {source}}) == [duplicate]
    duplicate.unlink()
    assert conflicting_sources([common, native], {'ls-context': {source}}) == []


def test_planned_destination_does_not_accept_same_bytes_elsewhere(tmp_path):
    planned = skill(tmp_path / 'common/ls-context')
    duplicate = skill(tmp_path / 'native/ls-context')
    assert conflicting_sources([tmp_path / 'common', tmp_path / 'native'],
                               {'ls-context': {planned}}) == [duplicate]


def test_unknown_metadata_and_cycles_do_not_return_partial_success(tmp_path):
    bad = skill(tmp_path / 'bad')
    bad.write_text('---\nname: one\nname: two\n---\n')
    with pytest.raises(ValueError):
        conflicting_sources([bad.parent], {'ls-context': set()})
    bad.unlink()
    (bad.parent / 'cycle').symlink_to(bad.parent, target_is_directory=True)
    with pytest.raises(ValueError, match='cycle'):
        conflicting_sources([bad.parent], {})


def test_scan_budget_is_shared_and_metadata_symlinks_are_not_opened(tmp_path):
    root = tmp_path / 'root';root.mkdir();(root / 'entry').write_text('fixture')
    with pytest.raises(ValueError, match='4096'):
        list(skill_sources(root, [4096]))
    outside = skill(tmp_path / 'outside')
    (root / 'SKILL.md').symlink_to(outside)
    with pytest.raises(OSError):
        conflicting_sources([root], {})
