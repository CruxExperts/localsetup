import argparse
from pathlib import Path

import pytest

from ls.core.cli_parser import build_parser
from ls.core.docs_alignment.inventory import _cli_commands


def test_command_inventory_matches_runtime_root_parser():
    root = Path(__file__).resolve().parents[2]
    parser = build_parser(*(lambda *args, **kwargs: None for _ in range(4)))
    choices = next(action.choices for action in parser._actions if isinstance(action, argparse._SubParsersAction))
    assert _cli_commands(root) == sorted(choices)
    assert {'agent', 'llm', 'harness', 'publish-preflight'} <= set(choices)


def test_static_inventory_handles_formatting_without_running_source(tmp_path):
    source = tmp_path/'ls/core/cli_parser.py'
    source.parent.mkdir(parents=True)
    source.write_text("raise RuntimeError('must not execute')\ndef build_parser():\n"
                      "    sub.add_parser(\n        'one'\n    )\n    sub.add_parser(\"two\")\n"
                      "    nested_sub.add_parser('nested')\n")
    assert _cli_commands(tmp_path) == ['one', 'two']


@pytest.mark.parametrize('source', ['', 'def build_parser():\n    pass',
                                 "def build_parser():\n    sub.add_parser(name)", 'def broken('])
def test_missing_parser_contract_fails_visibly(tmp_path, source):
    path = tmp_path/'ls/core/cli_parser.py'
    path.parent.mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        _cli_commands(tmp_path)
    path.write_text(source)
    with pytest.raises((ValueError, SyntaxError)):
        _cli_commands(tmp_path)
