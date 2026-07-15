#!/usr/bin/env python3
"""Verify the packaged Scrapling capability index without side effects."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


CAPABILITY_RELATIVE_PATH = Path("ls/tools/scrapling_helper/scrapling_capabilities.json")
REQUIRED_CAPABILITIES = (
    "scrapling_status",
    "extract_url_simple",
    "extract_url_structured",
    "run_spider",
    "scrapling_job_status",
    "scrapling_cancel_job",
    "upgrade_scrapling",
    "refresh_adapters",
    "scrapling_self_test",
)
REQUIRED_FIELDS = ("cli", "helper", "description")


def _candidate_roots() -> list[Path]:
    roots: list[Path] = []
    for start in (Path.cwd(), Path(__file__).resolve()):
        for candidate in (start, *start.parents):
            if candidate not in roots:
                roots.append(candidate)
    return roots


def find_capability_index() -> Path:
    for root in _candidate_roots():
        candidate = root / CAPABILITY_RELATIVE_PATH
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"could not find {CAPABILITY_RELATIVE_PATH}")


def load_capabilities(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def verify_capabilities(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for name in REQUIRED_CAPABILITIES:
        capability = data.get(name)
        if not isinstance(capability, dict):
            errors.append(f"missing capability object: {name}")
            continue
        for field in REQUIRED_FIELDS:
            if not isinstance(capability.get(field), str) or not capability[field].strip():
                errors.append(f"{name} missing non-empty string field: {field}")
    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify Localsetup's packaged Scrapling capability index.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print a JSON result instead of a short text summary.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        path = find_capability_index()
        data = load_capabilities(path)
        errors = verify_capabilities(data)
    except (FileNotFoundError, ValueError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "errors": [str(exc)]}, sort_keys=True))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    payload = {
        "ok": not errors,
        "path": str(path),
        "checked": list(REQUIRED_CAPABILITIES),
        "errors": errors,
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    elif errors:
        print("\n".join(f"ERROR: {error}" for error in errors), file=sys.stderr)
    else:
        print(f"OK: verified {len(REQUIRED_CAPABILITIES)} Scrapling capabilities")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
