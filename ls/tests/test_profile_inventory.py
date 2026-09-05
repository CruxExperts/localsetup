import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ls.core.agent.profile_inventory import inventory
from ls.core.agent.profiles import load


def configuration(tmp_path):
    profile = {'base_url': 'https://private.example/v1/', 'api': 'chat_completions',
               'model': 'test-model', 'credential_env': 'PRIVATE_CREDENTIAL_NAME',
               'timeout_seconds': 10, 'capabilities': ['tools', 'streaming'],
               'allow_loopback_http': False}
    path = tmp_path / 'profiles.json'
    path.write_text(json.dumps({'schema_version': 1, 'profiles': {'selected': profile}}))
    return path, profile


def test_inventory_no_credentials_or_state_and_load_compatibility(tmp_path):
    path, _ = configuration(tmp_path)
    before = path.read_bytes()
    report = inventory(path)
    assert report == {'schema_version': 1, 'profiles': [{'name': 'selected', 'model': 'test-model',
        'api': 'chat_completions', 'capabilities': ['streaming', 'tools']}]}
    assert load(path, 'selected').model == 'test-model'
    assert path.read_bytes() == before and list(tmp_path.iterdir()) == [path]
    assert 'private' not in json.dumps(report).lower()
    with pytest.raises(ValueError): load(path, 'unknown')


@pytest.mark.parametrize('kind', ['duplicate', 'oversized', 'invalid', 'count', 'name', 'symlink'])
def test_inventory_refuses_invalid_config_without_partial_output(tmp_path, kind):
    path, profile = configuration(tmp_path)
    if kind == 'duplicate': path.write_text('{"schema_version":1,"profiles":{},"profiles":{}}')
    elif kind == 'oversized': path.write_text(' ' * (1024 * 1024 + 1))
    elif kind == 'invalid':
        path.write_text(json.dumps({'schema_version':1, 'profiles': {'good': profile, 'bad': {}}}))
    elif kind == 'count':
        path.write_text(json.dumps({'schema_version':1, 'profiles': {str(n): profile for n in range(257)}}))
    elif kind == 'name':
        path.write_text(json.dumps({'schema_version':1, 'profiles': {'x'*257: profile}}))
    else:
        target = tmp_path/'target'; path.rename(target); path.symlink_to(target)
    with pytest.raises(ValueError): inventory(path)


def test_cli_provider_free_safe_rendering_and_sanitized_error(tmp_path):
    path, profile = configuration(tmp_path)
    path.write_text(json.dumps({'schema_version':1, 'profiles': {'z\x1b[31m\nspoof': profile, 'a': profile}}))
    script = '''
import sys
from ls.core.agent.cli import main
result=main(sys.argv[1:])
assert not any(k.startswith(('pydantic_ai','openai','httpx')) for k in sys.modules)
raise SystemExit(result)
'''
    env = dict(os.environ); env.pop('PRIVATE_CREDENTIAL_NAME', None)
    command = [sys.executable, '-c', script, 'profiles', '--profiles', str(path)]
    result = subprocess.run(command, capture_output=True, text=True, env=env)
    assert result.returncode == 0 and '\x1b' not in result.stdout
    assert result.stdout.startswith('"a":') and len(result.stdout.splitlines()) == 2 and 'private' not in result.stdout.lower()
    result = subprocess.run([*command, '--format', 'json'], capture_output=True, text=True, env=env)
    assert result.returncode == 0 and len(json.loads(result.stdout)['profiles']) == 2
    path.write_text('SECRET_INVALID_CONFIG')
    result = subprocess.run(command, capture_output=True, text=True, env=env)
    assert result.returncode == 2 and not result.stdout
    assert 'SECRET' not in result.stderr and str(path) not in result.stderr


def test_inventory_failure_full_stderr_is_bounded(tmp_path):
    import time
    from ls.core.agent.cli import main
    read, write = os.pipe(); saved = os.dup(2)
    try:
        os.set_blocking(write, False)
        while True:
            try: os.write(write, b'x'*4096)
            except BlockingIOError: break
        os.set_blocking(write, True); os.dup2(write, 2)
        start = time.monotonic()
        assert main(['profiles', '--profiles', str(tmp_path/'missing')]) == 2
        assert time.monotonic()-start < 1 and os.get_blocking(write)
    finally:
        os.dup2(saved, 2)
        for fd in (read, write, saved): os.close(fd)
