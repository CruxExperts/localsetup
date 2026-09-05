"""Framework forwarding must preserve the LSCli command and authority boundary."""
import subprocess
import sys
from pathlib import Path

import pytest

from ls.core import cli
from ls.core.agent import cli as agent_cli


def test_forwarding_preserves_arguments_and_outcome(monkeypatch):
    arguments = ['run', '--profile', 'explicit', '--prompt-stdin', '--format', 'jsonl']
    seen = []
    monkeypatch.setattr(agent_cli, 'main', lambda value: seen.append(value) or 130)
    monkeypatch.setattr(cli, '_main', lambda value: pytest.fail('framework dispatcher used'))
    assert cli.main(['agent', *arguments]) == 130
    assert seen == [arguments]
    monkeypatch.setattr(sys, 'argv', ['localsetup', 'agent', *arguments])
    assert cli.main() == 130
    assert seen == [arguments, arguments]


def test_framework_selectors_do_not_become_agent_authority(monkeypatch, capsys):
    monkeypatch.setattr(agent_cli, 'main', lambda value: pytest.fail('agent launched'))
    with pytest.raises(SystemExit) as error:
        cli.main(['--home', '/nonexistent', 'agent', 'sessions'])
    assert error.value.code == 2
    assert 'place agent immediately' in capsys.readouterr().err


def test_help_and_version_match_without_provider_imports(tmp_path):
    root = Path(__file__).resolve().parents[2]
    script = '''
import contextlib, io, sys
from ls.core.cli import main
from ls.core.agent.cli import main as direct
for arguments in (['--help'], ['--version'], ['run', '--help']):
    outputs = []
    for function, prefix in ((main, ['agent']), (direct, [])):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            try: function(prefix + arguments)
            except SystemExit as error: assert error.code == 0
        outputs.append(output.getvalue())
    assert outputs[0] == outputs[1]
assert not any(name.split('.')[0] in {'pydantic_ai', 'pydantic_graph', 'openai', 'httpx'} for name in sys.modules)
'''
    result = subprocess.run([sys.executable, '-c', script], cwd=root, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
