import argparse
import json
from pathlib import Path
from types import SimpleNamespace

from ls.core import cli, installed_source


def test_distribution_record_must_match_running_module(tmp_path, monkeypatch):
    module = tmp_path / 'ls/core/cli.py'
    dist = SimpleNamespace(files=[Path('ls/core/cli.py')], locate_file=lambda entry: tmp_path / entry,
                           read_text=lambda name: 'present' if name in {'RECORD', 'WHEEL'} else None)
    monkeypatch.setattr(installed_source, 'distribution', lambda name: dist)
    assert installed_source.wheel_module(module)
    assert not installed_source.wheel_module(tmp_path / 'checkout/ls/core/cli.py')
    dist.read_text = lambda name: None
    assert not installed_source.wheel_module(module)  # SOURCES-only metadata.
    dist.read_text = lambda name: '{"dir_info":{"editable":true}}' if name == 'direct_url.json' else 'present'
    assert not installed_source.wheel_module(module)
    dist.read_text = lambda name: 'present' if name in {'RECORD', 'WHEEL'} else None
    dist.files = [Path('editable.pth')]
    assert not installed_source.wheel_module(module)


def test_wheel_target_default_and_explicit_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(installed_source, 'wheel_module', lambda path: True)
    monkeypatch.setattr(cli, '_is_global_shim_invocation', lambda: False)
    monkeypatch.setattr(cli, 'detect_invocation_target', lambda: tmp_path / 'caller')
    args = argparse.Namespace(cmd='plan', target_directory=None, config=None)
    cli._inject_global_target(args)
    assert args.target_directory == str(tmp_path / 'caller')
    assert args.detected_target_directory
    args.target_directory = str(tmp_path / 'explicit')
    cli._inject_global_target(args)
    assert args.target_directory == str(tmp_path / 'explicit')
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'target_directory': str(tmp_path / 'configured')}))
    args = argparse.Namespace(cmd='plan', target_directory=None, config=str(config))
    cli._inject_global_target(args)
    assert args.target_directory is None
    assert cli._resolved_config(args, tmp_path).target_directory == str(tmp_path / 'configured')


def test_source_checkout_default_and_non_target_command_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(installed_source, 'wheel_module', lambda path: False)
    monkeypatch.setattr(cli, '_is_global_shim_invocation', lambda: False)
    args = argparse.Namespace(cmd='plan', target_directory=None, config=None)
    cli._inject_global_target(args)
    assert args.target_directory is None
    monkeypatch.setattr(installed_source, 'wheel_module', lambda path: True)
    args.cmd = 'test-workers'
    cli._inject_global_target(args)
    assert args.target_directory is None
