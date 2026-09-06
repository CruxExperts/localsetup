from pathlib import Path

import pytest

from ls.core.models import PlanAction
from ls.core.personal_adapter import write_entries


def test_entry_writer_rejects_outside_boundary_and_unsafe_names_before_writes(tmp_path):
    root = tmp_path / 'repo';library = tmp_path / 'library'
    journal = {'version': 1, 'touched': []}
    receipt = tmp_path / 'journal.json'
    action = PlanAction('attach_repo_path', tmp_path / 'outside', {'global_root': str(library), 'mode': 'symlink'})
    with pytest.raises(ValueError, match='escapes home'):write_entries(root, action, [], journal, receipt)
    action.path = root / '.cursor/skills'
    with pytest.raises(ValueError, match='Invalid adapter package name'):
        write_entries(root, action, ['../outside'], journal, receipt)
    assert not root.exists() and not receipt.exists()
