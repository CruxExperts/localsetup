import json
from dataclasses import replace

import pytest

from ls.core.config import (
    InstallConfig, config_to_dict, load_install_config, merge_cli_config,
    validate_install_config,
)


def test_scope_config_preserves_omission_and_explicit_selection(tmp_path):
    path = tmp_path / 'install.json'
    for scope in (None, 'repo', 'personal', 'both'):
        path.write_text(json.dumps({'skill_scope': scope, 'platforms': []}))
        config = load_install_config(path)
        assert config.skill_scope == scope
        assert config.platforms == []
        assert config_to_dict(config)['skill_scope'] == scope
        assert merge_cli_config(config).skill_scope == scope
        assert merge_cli_config(config, skill_scope='both').skill_scope == 'both'
        assert merge_cli_config(config).platforms == []
    path.write_text('{}')
    config = load_install_config(path)
    assert config.skill_scope is None and config.platforms is None
    assert merge_cli_config(config, skill_scope='personal').platforms is None


@pytest.mark.parametrize('scope', ['', 'all', 1, True, [], {}])
def test_invalid_scope_rejected_with_and_without_schema(tmp_path, scope, monkeypatch):
    import ls.core.config as config_module
    path = tmp_path / 'install.json'
    path.write_text(json.dumps({'skill_scope': scope}))
    with pytest.raises(ValueError):
        load_install_config(path)
    monkeypatch.setattr(config_module, '_validate_against_schema', lambda *_: None)
    with pytest.raises(ValueError):
        load_install_config(path)
    with pytest.raises(ValueError):
        validate_install_config(replace(InstallConfig(), skill_scope=scope))
    with pytest.raises(ValueError):
        merge_cli_config(InstallConfig(), skill_scope=scope)
