from pathlib import Path
import json
import subprocess
import sys

from ls.core.agent import cli, diagnostics

ROOT = Path(__file__).resolve().parents[2]


def test_provider_free_import_and_help_from_outside_checkout(tmp_path):
    code = '''import sys
sys.path.insert(0, sys.argv[1])
from ls.core.agent.cli import main
try:
    main(["--help"])
except SystemExit as e:
    assert e.code == 0
assert not any(n.startswith(("pydantic_ai", "pydantic_graph", "openai", "httpx", "yaml")) for n in sys.modules)
'''
    result = subprocess.run([sys.executable, '-I', '-S', '-c', code, str(ROOT)], cwd=tmp_path, capture_output=True, text=True, check=True)
    assert 'LSCli' in result.stdout and 'doctor' in result.stdout


def test_missing_and_invalid_payload_inspection_never_creates_user_state(tmp_path):
    package = tmp_path / 'package'
    home = tmp_path / 'absent-home'
    report = diagnostics.inspect(package_root=package, home=home)
    assert report['sdk_payload'] == 'missing'
    assert report['execution_available'] is False
    assert not home.exists()
    payload = package / '_sdk_payload'
    payload.mkdir(parents=True)
    (payload / 'manifest.json').write_text('{}')
    assert diagnostics.inspect(package_root=package, home=home)['sdk_payload'] == 'invalid'
    assert not home.exists()


def test_cli_version_json_and_default_outcomes(capfd, monkeypatch, tmp_path):
    import pytest
    with pytest.raises(SystemExit) as e:
        cli.main(['--version'])
    assert e.value.code == 0
    assert 'LSCli (LocalSetup)' in capfd.readouterr().out
    monkeypatch.setattr(cli, 'inspect', lambda: diagnostics.inspect(package_root=tmp_path, home=tmp_path / 'home'))
    assert cli.main(['doctor', '--format', 'json']) == 3
    output = capfd.readouterr()
    assert not output.err and json.loads(output.out)['status'] == 'not_ready'
    assert cli.main([]) == 3
    output = capfd.readouterr()
    assert not output.out and 'lscli doctor' in output.err


def test_unhashable_manifest_field_returns_invalid_payload(tmp_path):
    payload = tmp_path / '_sdk_payload'
    payload.mkdir()
    (payload / 'manifest.json').write_text(json.dumps({
        'schema_version': 1, 'components': [{'name': []}, {}, {}],
    }))
    assert diagnostics.inspect(package_root=tmp_path, home=tmp_path)['sdk_payload'] == 'invalid'


def test_inaccessible_payload_probe_returns_invalid_payload(tmp_path, monkeypatch):
    def inaccessible(path):
        raise PermissionError('denied')
    monkeypatch.setattr(Path, 'exists', inaccessible)
    assert diagnostics.inspect(package_root=tmp_path, home=tmp_path)['sdk_payload'] == 'invalid'
