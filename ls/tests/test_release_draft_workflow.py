"""Exercise the actual release shell boundary with offline GitHub responses."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml


@pytest.mark.parametrize("response,tag_conflict,created", [
    ("missing", False, True),
    ("exists", False, False),
    ("uncertain", False, False),
    ("missing", True, False),
])
def test_release_is_only_created_as_draft(tmp_path, response, tag_conflict, created):
    root = Path(__file__).resolve().parents[2]
    workflow = yaml.safe_load((root / ".github/workflows/publish.yml").read_text())
    steps = workflow["jobs"]["publish"]["steps"]
    script = next(s["run"] for s in steps if s["name"] == "Prepare GitHub release draft")
    (tmp_path / "VERSION").write_text("4.22.7\n")
    for command in ("git", "gh", "uv"):
        executable = tmp_path / command
        executable.write_text(f"#!{sys.executable}\n" + '''
import json, os, pathlib, sys
args = sys.argv[1:]
if pathlib.Path(sys.argv[0]).name == 'uv':
    print('Verified release notes')
elif pathlib.Path(sys.argv[0]).name == 'git':
    if args[:2] == ['rev-parse', '-q']:
        sys.exit(0 if os.environ['TAG_CONFLICT'] == '1' else 1)
    print('prior' if args[0] == 'rev-list' else 'accepted')
elif args[0] == 'api':
    mode = os.environ['RELEASE_RESPONSE']
    print('HTTP/2.0 ' + {'missing': '404 Not Found', 'exists': '200 OK', 'uncertain': '503 Unavailable'}[mode])
    sys.exit(0 if mode == 'exists' else 1)
else:
    pathlib.Path('mutation.json').write_text(json.dumps(args))
''')
        executable.chmod(0o700)
    env = {**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
        "GITHUB_REPOSITORY": "example/project", "GITHUB_SHA": "original", "RELEASE_COMMIT": "accepted",
        "RELEASE_DOCS_STATE": ".agents/state/test-release-docs",
        "RELEASE_RESPONSE": response, "TAG_CONFLICT": str(int(tag_conflict))}
    result = subprocess.run(["bash", "-c", script], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=10)
    assert (result.returncode == 0) is created, result.stderr
    mutation = tmp_path / "mutation.json"
    assert mutation.exists() is created
    if created:
        args = json.loads(mutation.read_text())
        assert args[:3] == ["release", "create", "v4.22.7"]
        assert "--draft" in args and "--clobber" not in args
        assert args[args.index("--target") + 1] == "accepted"
        assert "--notes-file" in args
        assert len([a for a in args if a.startswith("dist/")]) == 3
