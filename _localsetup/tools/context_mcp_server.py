#!/usr/bin/env python3
"""Optional MCP entry point for Localsetup context-index.

The core context index intentionally has no MCP dependency. This wrapper is the
stable command target emitted by `context-index mcp config`; environments that
install the MCP Python SDK can extend this file into a live stdio server without
changing agent configuration.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="context_mcp_server")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--home", default=str(Path.home()))
    parser.add_argument("--transport", default="stdio", choices=["stdio"])
    parser.add_argument("--read-only", action="store_true", default=True)
    parser.parse_args(argv)
    print(
        json.dumps(
            {
                "ok": False,
                "error": {
                    "code": "MCP_SERVER_OPTIONAL",
                    "message": "The context-index MCP server wrapper is present, but the MCP SDK server implementation is not enabled in this build.",
                    "recommended_action": "Use the deterministic CLI or install/enable the MCP SDK wrapper before serving over stdio.",
                },
            },
            indent=2,
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
