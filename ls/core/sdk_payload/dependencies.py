"""Export managed external dependency locks through the owning uv resolver."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

OUTPUTS = {"runtime": "sdk-runtime.lock", "build": "sdk-build.lock"}


def exports(root: Path) -> dict[str, bytes]:
    """Use locked, offline exports; do not resolve or install dependencies."""
    result = {}
    for scope, filename in OUTPUTS.items():
        selection = ["--no-default-groups"] if scope == "runtime" else ["--only-group", "sdk-build"]
        command = [
            "uv", "export", "--locked", "--offline", "--no-header", "--no-annotate",
            "--no-emit-project", "--format", "requirements.txt", *selection,
        ]
        output = subprocess.run(command, cwd=root, check=True, capture_output=True).stdout
        # Never turn an empty export or accidental upstream SDK installation into a lock.
        if not output.strip() or b"--hash=sha256:" not in output:
            raise ValueError(f"Invalid {scope} dependency export")
        for line in output.decode("utf-8").splitlines():
            name = line.split("==", 1)[0].lower().replace("_", "-")
            if name in {"localsetup", "pydantic-ai-slim", "pydantic-graph", "pydantic-ai-harness"}:
                raise ValueError(f"Unexpected distribution in {scope} dependency export: {name}")
        result[filename] = output
    return result


def refresh(root: Path, *, check: bool) -> list[str]:
    """Check exact generator output, or replace only its two owned regular files."""
    expected = exports(root)
    directory = root / "ls" / "config"
    if any(p.is_symlink() for p in (directory, *directory.parents)):
        raise ValueError("Dependency lock directory must not contain symlinks")
    targets = {directory / name: data for name, data in expected.items()}
    for path in targets:
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError(f"Dependency lock must be a regular file: {path.name}")
    changed = [path.name for path, data in targets.items() if not path.exists() or path.read_bytes() != data]
    if not check:
        for path, data in targets.items():
            if path.name in changed:
                path.write_bytes(data)
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate or check managed dependency locks")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true", help="Report drift without writing")
    args = parser.parse_args(argv)
    try:
        changed = refresh(args.repo_root.absolute(), check=args.check)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Dependency lock export failed: {exc}", file=sys.stderr)
        return 2
    if changed:
        print(("Stale: " if args.check else "Updated: ") + ", ".join(changed))
    return 1 if args.check and changed else 0
