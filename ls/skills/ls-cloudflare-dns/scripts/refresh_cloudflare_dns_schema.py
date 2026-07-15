#!/usr/bin/env python3
"""Record the Cloudflare DNS API schema source used by this skill."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

for parent in Path(__file__).resolve().parents:
    if (parent / "lib" / "deps.py").is_file():
        sys.path.insert(0, str(parent / "lib"))
        from deps import require_deps

        require_deps(["requests"])
        break

try:
    import requests
except ImportError as exc:  # pragma: no cover - environment guidance
    raise SystemExit("Missing dependency: requests. Run `uv sync --locked --no-dev` from the Localsetup source checkout.") from exc


DEFAULT_OPENAPI_URL = "https://raw.githubusercontent.com/cloudflare/api-schemas/main/openapi.json"


def load_schema(url: str, timeout: float) -> dict[str, Any]:
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("OpenAPI response was not a JSON object.")
    return data


def summarize_dns_paths(schema: dict[str, Any]) -> dict[str, Any]:
    paths = schema.get("paths", {})
    if not isinstance(paths, dict):
        paths = {}
    dns_paths = sorted(path for path in paths if "/dns" in path or path in {"/zones", "/zones/{zone_id}", "/zones/{zone_id}/settings", "/zones/{zone_id}/settings/{setting_id}"})
    return {
        "source": DEFAULT_OPENAPI_URL,
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "dns_path_count": len(dns_paths),
        "dns_paths": dns_paths,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh the local Cloudflare DNS OpenAPI path summary.")
    parser.add_argument("--url", default=DEFAULT_OPENAPI_URL)
    parser.add_argument("--output", default=str(Path(__file__).resolve().parents[1] / "references" / "cloudflare-openapi-dns-paths.json"))
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)

    schema = load_schema(args.url, args.timeout)
    summary = summarize_dns_paths(schema)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(output), "dns_path_count": summary["dns_path_count"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
