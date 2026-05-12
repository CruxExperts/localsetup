#!/usr/bin/env python3
"""Validate the Cloudflare DNS skill package structure and JSON schemas."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    import jsonschema
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Missing dependency: jsonschema. Install _localsetup/requirements.txt.") from exc


SKILL_ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def validate_instance(schema_name: str, fixture_name: str) -> None:
    schema = load_json(SKILL_ROOT / "schemas" / schema_name)
    fixture = load_json(SKILL_ROOT / "tests" / "fixtures" / fixture_name)
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(fixture, schema)


def validate_openapi_summary() -> None:
    summary = load_json(SKILL_ROOT / "references" / "cloudflare-openapi-dns-paths.json")
    required_paths = {
        "/zones",
        "/zones/{zone_id}",
        "/zones/{zone_id}/dns_settings",
        "/zones/{zone_id}/dns_records",
        "/zones/{zone_id}/dns_records/{dns_record_id}",
        "/zones/{zone_id}/dns_records/batch",
        "/zones/{zone_id}/dns_records/import",
        "/zones/{zone_id}/dns_records/export",
        "/zones/{zone_id}/dns_records/scan/trigger",
        "/zones/{zone_id}/dns_records/scan/review",
        "/zones/{zone_id}/settings",
        "/zones/{zone_id}/settings/{setting_id}",
    }
    paths = set(summary.get("dns_paths") or [])
    missing = sorted(required_paths - paths)
    if missing:
        raise ValueError(f"OpenAPI DNS path summary missing required paths: {missing}")
    if not summary.get("source") or not isinstance(summary.get("dns_path_count"), int):
        raise ValueError("OpenAPI DNS path summary missing source or dns_path_count.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate ls-cloudflare-dns files and fixtures.")
    parser.parse_args(argv)

    required = [
        "SKILL.md",
        "scripts/cf_dns.py",
        "scripts/refresh_cloudflare_dns_schema.py",
        "schemas/cli-output.schema.json",
        "schemas/dns-change-plan.schema.json",
        "schemas/dns-snapshot.schema.json",
        "schemas/dns-record-normalized.schema.json",
        "references/source-ledger.md",
        "references/api-scope.md",
        "references/auth-permissions.md",
        "references/cloudflare-openapi-dns-paths.json",
        "references/safety.md",
    ]
    missing = [item for item in required if not (SKILL_ROOT / item).exists()]
    if missing:
        print(json.dumps({"ok": False, "missing": missing}, indent=2, sort_keys=True))
        return 1

    validate_instance("dns-record-normalized.schema.json", "normalized-record.json")
    validate_instance("dns-snapshot.schema.json", "snapshot.json")
    validate_instance("dns-change-plan.schema.json", "change-plan.json")
    validate_instance("cli-output.schema.json", "cli-output.json")
    validate_openapi_summary()
    print(json.dumps({"ok": True, "validated": required}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
