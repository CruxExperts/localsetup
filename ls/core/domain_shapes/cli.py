from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .compiler import compile_domain
from .config import validate_domain_shapes
from .models import DomainShapesError


def _error_payload(exc: DomainShapesError) -> dict[str, Any]:
    return {"ok": False, "error": str(exc), "issues": list(exc.issues)}


def handle(cli, args, root: Path, home: Path) -> int | None:
    if args.cmd != "domain":
        return None
    config_path = Path(args.config).expanduser()
    schema_path = root / "ls" / "config" / "domain-shapes.schema.json"
    if not schema_path.is_file():
        schema_path = None
    try:
        if args.domain_action == "validate":
            payload = validate_domain_shapes(config_path, schema_path=schema_path)
        else:
            result = compile_domain(
                config_path,
                args.domain,
                Path(args.directory).expanduser(),
                schema_path=schema_path,
            )
            payload = dict(result)
    except DomainShapesError as exc:
        payload = _error_payload(exc)
    except (OSError, TypeError, ValueError) as exc:
        payload = {"ok": False, "error": str(exc), "issues": [str(exc)]}
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    return 0 if payload.get("ok") else 1


__all__ = ["handle"]
