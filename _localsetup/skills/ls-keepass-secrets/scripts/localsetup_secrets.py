#!/usr/bin/env python3
"""JSON-first Localsetup KeePass secrets helper."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - exercised by environments
    raise SystemExit("PyYAML is required; install _localsetup/requirements.txt") from exc

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from fake_vault_backend import FakeVaultBackend, generate_password  # noqa: E402

ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
ALIAS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9@._:+-]{0,191}$")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
SECRET_REF_RE = re.compile(r"\{\{secret:([^}:]+):([^}]+)\}\}")
SECRET_ID_LINE_RE = re.compile(r"^Secret ID:\s*([A-Za-z0-9@._:+-]+)\s*$")
SECRET_URI_RE = re.compile(
    r"^secret://localsetup/([a-z0-9_-]+)/([a-z0-9_-]+)/([a-z0-9][a-z0-9._-]{0,127})(?:#field=([A-Za-z0-9_.-]+))?$"
)
SAFE_WRITE_FIELDS = {"username", "password", "url", "notes", "UserName", "Password", "URL", "Notes", "title", "path"}
SENSITIVE_KEYS = {"password", "token", "secret", "key", "passphrase", "private_key", "Password"}
SECRET_KEY_PARTS = (
    "password",
    "passwd",
    "pwd",
    "token",
    "secret",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
    "key_material",
    "passphrase",
)
ENV_PREFIX = "LOCALSETUP_SECRETS_"


class CliError(Exception):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass
class ResolvedConfig:
    repo_root: Path
    config: dict[str, Any]
    map_path: Path | None
    sources: list[str]


def clean_text(value: Any, *, label: str, max_len: int = 4096, required: bool = False) -> str:
    if value is None:
        if required:
            raise CliError("invalid_input", f"{label} is required")
        return ""
    if not isinstance(value, str):
        raise CliError("invalid_input", f"{label} must be a string")
    value = CONTROL_RE.sub(" ", value).strip()
    if required and not value:
        raise CliError("invalid_input", f"{label} is required")
    if len(value) > max_len:
        raise CliError("invalid_input", f"{label} exceeds {max_len} characters")
    return value


def validate_id(secret_id: str) -> str:
    secret_id = clean_text(secret_id, label="secret id", max_len=128, required=True).lower()
    if not ID_RE.fullmatch(secret_id):
        raise CliError("invalid_secret_id", f"Invalid canonical secret id: {secret_id}")
    return secret_id


def validate_alias(alias: str) -> str:
    alias = clean_text(alias, label="alias", max_len=192, required=True)
    if ID_RE.fullmatch(alias.lower()):
        return alias.lower()
    if not ALIAS_RE.fullmatch(alias):
        raise CliError("invalid_alias", f"Invalid alias: {alias}")
    return alias


def read_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
    except OSError as exc:
        raise CliError("read_failed", f"Could not read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise CliError("invalid_yaml", f"Invalid YAML in {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise CliError("invalid_yaml", f"{path} must contain a YAML mapping")
    reject_secret_values(data, source=str(path))
    return data


def reject_secret_values(value: Any, *, source: str, path: str = "") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_s = str(key)
            next_path = f"{path}.{key_s}" if path else key_s
            lowered = key_s.lower()
            if is_sensitive_key(key_s) and item not in (None, "", "prompt"):
                raise CliError("secret_value_in_file", f"{source} contains secret-like value at {next_path}")
            reject_secret_values(item, source=source, path=next_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            reject_secret_values(item, source=source, path=f"{path}[{index}]")


def find_repo_root(start: Path) -> Path:
    current = start.resolve()
    for path in (current, *current.parents):
        if (path / "_localsetup").is_dir():
            return path
    return current


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def resolve_config(args: argparse.Namespace) -> ResolvedConfig:
    repo_root = Path(args.repo_root).expanduser().resolve() if getattr(args, "repo_root", None) else find_repo_root(Path.cwd())
    config: dict[str, Any] = {
        "backend": "keepassxc",
        "scope": "repo",
        "profile": "default",
        "keepassxc_binary": "keepassxc-cli",
    }
    sources: list[str] = []
    candidate_configs = [
        Path.home() / ".config" / "localsetup" / "secrets" / "config.yaml",
        repo_root / "secrets" / "keepass-config.yaml",
        repo_root / ".localsetup" / "secrets" / "config.yaml",
    ]
    for path in candidate_configs:
        if path.is_file():
            config = deep_merge(config, read_yaml(path))
            sources.append(str(path))
    env_map = {
        "BACKEND": "backend",
        "CONFIG": "config_path",
        "MAP": "map_path",
        "PROFILE": "profile",
        "SCOPE": "scope",
        "DATABASE": "database",
        "KEEPASSXC_BINARY": "keepassxc_binary",
        "FAKE_STORE": "fake_store",
    }
    for env_name, config_name in env_map.items():
        value = os.environ.get(f"{ENV_PREFIX}{env_name}")
        if value:
            config[config_name] = clean_text(value, label=f"{ENV_PREFIX}{env_name}")
            sources.append(f"env:{ENV_PREFIX}{env_name}")
    if getattr(args, "config", None):
        path = Path(args.config).expanduser().resolve()
        config = deep_merge(config, read_yaml(path))
        sources.append(str(path))
    for attr, key in (
        ("backend", "backend"),
        ("profile", "profile"),
        ("scope", "scope"),
        ("database", "database"),
        ("map", "map_path"),
        ("keepassxc_binary", "keepassxc_binary"),
        ("fake_store", "fake_store"),
    ):
        value = getattr(args, attr, None)
        if value:
            config[key] = clean_text(value, label=attr)
            sources.append(f"cli:{attr}")

    map_path = resolve_map_path(repo_root, config)
    return ResolvedConfig(repo_root=repo_root, config=config, map_path=map_path, sources=sources)


def resolve_map_path(repo_root: Path, config: dict[str, Any]) -> Path | None:
    if config.get("map_path"):
        path = Path(str(config["map_path"])).expanduser()
        return path if path.is_absolute() else (repo_root / path).resolve()
    repo_map = repo_root / ".localsetup" / "secrets" / "map.yaml"
    if repo_map.is_file():
        return repo_map
    legacy_maps = sorted((repo_root / "secrets").glob("*-secrets-map.yaml")) if (repo_root / "secrets").is_dir() else []
    if len(legacy_maps) == 1:
        return legacy_maps[0]
    if len(legacy_maps) > 1:
        return None
    global_map = Path.home() / ".local" / "share" / "localsetup" / "secrets" / "maps" / "default.yaml"
    return global_map if global_map.is_file() else None


def flatten_entries(entries: Any, prefix: tuple[str, ...] = ()) -> dict[str, dict[str, Any]]:
    flat: dict[str, dict[str, Any]] = {}
    if not isinstance(entries, dict):
        raise CliError("invalid_map", "entries must be a mapping")
    for key, value in entries.items():
        part = clean_text(str(key), label="entry key", max_len=128, required=True).lower()
        current = (*prefix, part)
        if isinstance(value, dict) and ("path" in value or "service_type" in value or "username" in value):
            secret_id = validate_id(".".join(current))
            item = dict(value)
            item["id"] = secret_id
            flat[secret_id] = item
        elif isinstance(value, dict):
            flat.update(flatten_entries(value, current))
        else:
            raise CliError("invalid_map", f"entry {'.'.join(current)} must be a mapping")
    return flat


def flatten_aliases(aliases: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    if aliases in (None, {}):
        return result
    if not isinstance(aliases, dict):
        raise CliError("invalid_map", "aliases must be a mapping")
    for key, value in aliases.items():
        if isinstance(value, str):
            alias = validate_alias(str(key))
            target = validate_id(value)
            if alias in result and result[alias] != target:
                raise CliError("ambiguous_alias", f"Alias {alias} maps to multiple ids")
            result[alias] = target
        elif isinstance(value, dict):
            nested = flatten_aliases(value)
            for alias, target in nested.items():
                if alias in result and result[alias] != target:
                    raise CliError("ambiguous_alias", f"Alias {alias} maps to multiple ids")
                result[alias] = target
        else:
            raise CliError("invalid_map", f"alias {key} must map to a string or mapping")
    return result


def load_map(config: ResolvedConfig) -> tuple[dict[str, dict[str, Any]], dict[str, str], list[str]]:
    if not config.map_path:
        return {}, {}, []
    data = read_yaml(config.map_path)
    entries = flatten_entries(data.get("entries", {}))
    aliases = flatten_aliases(data.get("aliases", {}))
    return entries, aliases, [str(config.map_path)]


def resolve_secret_id(raw: str, aliases: dict[str, str]) -> str:
    alias = validate_alias(raw)
    lowered = alias.lower()
    if lowered in aliases:
        return aliases[lowered]
    if alias in aliases:
        return aliases[alias]
    return validate_id(lowered)


def parse_reference(raw: str) -> dict[str, str]:
    text = clean_text(raw, label="reference", max_len=512, required=True)
    match = SECRET_ID_LINE_RE.fullmatch(text)
    if match:
        return {"id": validate_alias(match.group(1)), "field": "password", "type": "secret-id-line"}
    match = SECRET_REF_RE.fullmatch(text)
    if match:
        return {"id": validate_alias(match.group(1)), "field": clean_text(match.group(2), label="field", required=True), "type": "template"}
    match = SECRET_URI_RE.fullmatch(text)
    if match:
        return {
            "scope": match.group(1),
            "profile": match.group(2),
            "id": validate_id(match.group(3)),
            "field": match.group(4) or "password",
            "type": "uri",
        }
    return {"id": validate_alias(text), "field": "password", "type": "id"}


def redact(value: Any, redactions: list[str], path: str = "") -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            key_s = str(key)
            next_path = f"{path}.{key_s}" if path else key_s
            if is_sensitive_key(key_s):
                if item not in (None, ""):
                    redactions.append(next_path)
                result[key] = "<redacted>" if item not in (None, "") else item
            else:
                result[key] = redact(item, redactions, next_path)
        return result
    if isinstance(value, list):
        return [redact(item, redactions, f"{path}[{index}]") for index, item in enumerate(value)]
    return value


def is_sensitive_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return lowered in SENSITIVE_KEYS or any(part in lowered for part in SECRET_KEY_PARTS)


def envelope(
    command: str,
    data: Any = None,
    *,
    ok: bool = True,
    warnings: list[str] | None = None,
    errors: list[dict[str, Any]] | None = None,
    sources: list[str] | None = None,
    show_sensitive: bool = False,
    sensitive: bool = False,
) -> dict[str, Any]:
    redactions: list[str] = []
    rendered = data if show_sensitive else redact(data, redactions)
    return {
        "ok": ok,
        "command": command,
        "data": rendered,
        "warnings": warnings or [],
        "errors": errors or [],
        "sources": sources or [],
        "sensitive": bool(sensitive and show_sensitive),
        "redactions": sorted(set(redactions)),
    }


class KeePassXCBackend:
    name = "keepassxc"

    def __init__(self, binary: str) -> None:
        self.binary = binary
        self.path = shutil.which(binary)
        if not self.path:
            raise CliError("missing_backend", f"{binary} not found on PATH")

    def _run(self, argv: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self.path, *argv],
            shell=False,
            text=True,
            input=input_text,
            capture_output=True,
            timeout=60,
            check=False,
        )

    def info(self) -> dict[str, Any]:
        result = self._run(["--version"])
        version_text = "\n".join([result.stdout, result.stderr]).strip()
        return {"backend": self.name, "binary": self.path, "version": version_text}

    def resolve(self, secret_id: str, mapping: dict[str, Any] | None = None) -> dict[str, Any]:
        raise CliError(
            "interactive_backend_required",
            "KeePassXC reads require an interactive vault operation; use mapping validation or --backend fake for tests",
            details={"id": secret_id, "path": (mapping or {}).get("path")},
        )

    def list_entries(self) -> list[dict[str, Any]]:
        raise CliError("interactive_backend_required", "KeePassXC listing requires an interactive vault operation")

    def search(self, query: str) -> list[dict[str, Any]]:
        raise CliError("interactive_backend_required", "KeePassXC search requires an interactive vault operation")

    def ensure(
        self,
        items: list[dict[str, Any]],
        *,
        apply: bool = False,
        rotate: bool = False,
    ) -> dict[str, list[dict[str, str]]]:
        raise CliError("interactive_backend_required", "KeePassXC writes require an interactive vault operation")

    def set_field(self, secret_id: str, field: str, value: str, *, apply: bool = False) -> dict[str, Any]:
        if field not in SAFE_WRITE_FIELDS:
            raise CliError("unsupported_field", f"unsupported_field: {field}")
        raise CliError("interactive_backend_required", "KeePassXC field writes require an interactive vault operation")

    def delete(self, secret_id: str, *, apply: bool = False) -> dict[str, Any]:
        raise CliError("interactive_backend_required", "KeePassXC deletes require an interactive vault operation")


def backend_for(config: ResolvedConfig) -> Any:
    backend = clean_text(config.config.get("backend", "keepassxc"), label="backend").lower()
    if backend == "fake":
        store = config.config.get("fake_store")
        store_path = Path(str(store)).expanduser().resolve() if store else None
        return FakeVaultBackend(store_path)
    if backend == "keepassxc":
        return KeePassXCBackend(str(config.config.get("keepassxc_binary", "keepassxc-cli")))
    raise CliError("unsupported_backend", f"Unsupported backend: {backend}")


def command_doctor(args: argparse.Namespace) -> dict[str, Any]:
    config = resolve_config(args)
    data = {
        "repo_root": str(config.repo_root),
        "config": config.config,
        "map_path": str(config.map_path) if config.map_path else None,
        "python": sys.version.split()[0],
        "pyyaml": getattr(yaml, "__version__", "unknown"),
    }
    warnings: list[str] = []
    try:
        be = backend_for(config)
        data["backend"] = be.info()
    except CliError as exc:
        warnings.append(exc.message)
        data["backend"] = {"backend": config.config.get("backend"), "available": False}
    return envelope("doctor", data, warnings=warnings, sources=config.sources)


def command_config_show(args: argparse.Namespace) -> dict[str, Any]:
    config = resolve_config(args)
    return envelope("config-show", {"config": config.config, "map_path": str(config.map_path) if config.map_path else None}, sources=config.sources)


def command_config_init(args: argparse.Namespace) -> dict[str, Any]:
    config = resolve_config(args)
    target = config.repo_root / ".localsetup" / "secrets" / "config.yaml"
    sample = {
        "backend": args.backend or "keepassxc",
        "scope": args.scope or "repo",
        "profile": args.profile or "default",
        "map_path": ".localsetup/secrets/map.yaml",
        "keepassxc_binary": "keepassxc-cli",
    }
    if target.exists() and not args.apply:
        return envelope("config-init", {"path": str(target), "would_write": False, "exists": True}, warnings=["Use --apply to overwrite intentionally"])
    if args.apply:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(yaml.safe_dump(sample, sort_keys=False), encoding="utf-8")
    return envelope("config-init", {"path": str(target), "would_write": not args.apply, "config": sample})


def command_config_validate(args: argparse.Namespace) -> dict[str, Any]:
    config = resolve_config(args)
    errors = []
    if config.config.get("backend") not in {"keepassxc", "fake"}:
        errors.append({"code": "unsupported_backend", "message": "backend must be keepassxc or fake"})
    return envelope("config-validate", {"config": config.config}, ok=not errors, errors=errors, sources=config.sources)


def command_map_validate(args: argparse.Namespace) -> dict[str, Any]:
    config = resolve_config(args)
    entries, aliases, sources = load_map(config)
    return envelope("map-validate", {"entries": sorted(entries), "aliases": aliases, "count": len(entries)}, sources=config.sources + sources)


def command_list(args: argparse.Namespace) -> dict[str, Any]:
    config = resolve_config(args)
    entries, _, sources = load_map(config)
    be = backend_for(config)
    backend_entries = be.list_entries() if hasattr(be, "list_entries") else []
    return envelope("list", {"mapped": entries, "backend_entries": backend_entries}, sources=config.sources + sources)


def command_search(args: argparse.Namespace) -> dict[str, Any]:
    query = clean_text(args.query, label="query", max_len=128, required=True)
    config = resolve_config(args)
    entries, aliases, sources = load_map(config)
    mapped = {key: value for key, value in entries.items() if query.lower() in key or query.lower() in str(value).lower()}
    be = backend_for(config)
    backend_entries = be.search(query) if hasattr(be, "search") else []
    return envelope("search", {"mapped": mapped, "aliases": aliases, "backend_entries": backend_entries}, sources=config.sources + sources)


def command_reference(args: argparse.Namespace) -> dict[str, Any]:
    parsed = parse_reference(args.reference)
    return envelope("reference", parsed)


def command_resolve(args: argparse.Namespace) -> dict[str, Any]:
    config = resolve_config(args)
    entries, aliases, sources = load_map(config)
    parsed = parse_reference(args.id)
    secret_id = resolve_secret_id(parsed["id"], aliases)
    mapping = entries.get(secret_id, {})
    if secret_id not in entries and config.map_path:
        raise CliError("unknown_secret_id", f"{secret_id} is not present in the configured map")
    data = backend_for(config).resolve(secret_id, mapping)
    field = args.field or parsed.get("field")
    if field and field != "all":
        data = {"id": secret_id, field: data.get(field)}
    sensitive = bool(field in SENSITIVE_KEYS or "password" in data or "token" in data)
    if sensitive and not args.show_sensitive:
        data["_hint"] = "Use --show-sensitive to print protected values"
    return envelope("resolve", data, sources=config.sources + sources, show_sensitive=args.show_sensitive, sensitive=sensitive)


def _batch_items(args: argparse.Namespace, entries: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    if args.batch:
        path = Path(args.batch).expanduser().resolve()
        data = read_yaml(path)
        raw_items = data.get("items")
        if not isinstance(raw_items, list) or not raw_items:
            raise CliError("invalid_batch", "batch file must contain a non-empty items list")
        items = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                raise CliError("invalid_batch", "batch items must be mappings")
            item = dict(raw)
            item["id"] = validate_id(str(item.get("id", "")))
            items.append(item)
        return items
    secret_id = validate_id(args.id)
    item = dict(entries.get(secret_id, {}))
    item["id"] = secret_id
    if args.username:
        item["username"] = clean_text(args.username, label="username", max_len=256)
    return [item]


def command_ensure(args: argparse.Namespace) -> dict[str, Any]:
    config = resolve_config(args)
    entries, _, sources = load_map(config)
    items = _batch_items(args, entries)
    result = backend_for(config).ensure(items, apply=args.apply, rotate=args.rotate)
    return envelope("ensure", result, warnings=[] if args.apply else ["dry-run only; pass --apply to write"], sources=config.sources + sources)


def command_set(args: argparse.Namespace) -> dict[str, Any]:
    field = clean_text(args.field, label="field", max_len=64, required=True)
    if field not in SAFE_WRITE_FIELDS:
        raise CliError("unsupported_field", f"unsupported_field: {field}")
    value = sys.stdin.read() if args.stdin else args.value
    value = clean_text(value, label="value", max_len=65536, required=True)
    config = resolve_config(args)
    entries, aliases, sources = load_map(config)
    secret_id = resolve_secret_id(args.id, aliases)
    if config.map_path and secret_id not in entries:
        raise CliError("unknown_secret_id", f"{secret_id} is not present in the configured map")
    result = backend_for(config).set_field(secret_id, field, value, apply=args.apply)
    return envelope("set", result, warnings=[] if args.apply else ["dry-run only; pass --apply to write"], sources=config.sources + sources)


def command_rotate(args: argparse.Namespace) -> dict[str, Any]:
    config = resolve_config(args)
    entries, aliases, sources = load_map(config)
    secret_id = resolve_secret_id(args.id, aliases)
    item = dict(entries.get(secret_id, {}))
    item["id"] = secret_id
    item["password"] = generate_password()
    result = backend_for(config).ensure([item], apply=args.apply, rotate=True)
    return envelope("rotate", result, warnings=[] if args.apply else ["dry-run only; pass --apply to write"], sources=config.sources + sources)


def command_delete(args: argparse.Namespace) -> dict[str, Any]:
    config = resolve_config(args)
    _, aliases, sources = load_map(config)
    secret_id = resolve_secret_id(args.id, aliases)
    result = backend_for(config).delete(secret_id, apply=args.apply)
    return envelope("delete", result, warnings=[] if args.apply else ["dry-run only; pass --apply to write"], sources=config.sources + sources)


def command_audit(args: argparse.Namespace) -> dict[str, Any]:
    config = resolve_config(args)
    entries, aliases, sources = load_map(config)
    duplicate_paths: dict[str, list[str]] = {}
    for secret_id, item in entries.items():
        path = str(item.get("path", ""))
        if path:
            duplicate_paths.setdefault(path, []).append(secret_id)
    findings = [
        {"code": "duplicate_path", "path": path, "ids": ids}
        for path, ids in duplicate_paths.items()
        if len(ids) > 1
    ]
    return envelope("audit", {"entries": len(entries), "aliases": len(aliases), "findings": findings}, ok=not findings, sources=config.sources + sources)


def command_export_env(args: argparse.Namespace) -> dict[str, Any]:
    config = resolve_config(args)
    entries, aliases, sources = load_map(config)
    pairs: dict[str, str] = {}
    be = backend_for(config)
    for spec in args.vars:
        if "=" not in spec:
            raise CliError("invalid_input", "vars must use NAME=secret-id:field")
        name, ref = spec.split("=", 1)
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,127}", name):
            raise CliError("invalid_input", f"Invalid environment variable name: {name}")
        secret_part, _, field = ref.partition(":")
        secret_id = resolve_secret_id(secret_part, aliases)
        data = be.resolve(secret_id, entries.get(secret_id, {}))
        pairs[name] = str(data.get(field or "password", ""))
    return envelope("export-env", {"env": pairs}, sources=config.sources + sources, show_sensitive=args.show_sensitive, sensitive=True)


def command_render_template(args: argparse.Namespace) -> dict[str, Any]:
    template_path = Path(args.template).expanduser().resolve()
    text = template_path.read_text(encoding="utf-8", errors="replace")
    config = resolve_config(args)
    entries, aliases, sources = load_map(config)
    be = backend_for(config)
    used: list[str] = []

    def repl(match: re.Match[str]) -> str:
        secret_id = resolve_secret_id(match.group(1), aliases)
        field = match.group(2)
        used.append(secret_id)
        data = be.resolve(secret_id, entries.get(secret_id, {}))
        return str(data.get(field, ""))

    rendered = SECRET_REF_RE.sub(repl, text)
    output = getattr(args, "output", None)
    if output:
        if not args.show_sensitive:
            raise CliError("sensitive_output_requires_opt_in", "render-template --output requires --show-sensitive")
        output_path = Path(output).expanduser().resolve()
        if is_tracked_path(config.repo_root, output_path) and not args.allow_tracked_output:
            raise CliError("tracked_output_refused", f"Refusing to write sensitive rendered output to tracked path: {output_path}")
        if is_path_under(config.repo_root, output_path) and not is_ignored_path(config.repo_root, output_path) and not args.allow_unignored_output:
            raise CliError("tracked_output_refused", f"Refusing to write sensitive rendered output to non-ignored repo path: {output_path}")
        if args.apply:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(rendered, encoding="utf-8")
        data = {"output": str(output_path), "would_write": not args.apply, "used": sorted(set(used))}
    else:
        data = {"rendered": rendered if args.show_sensitive else "<redacted>", "used": sorted(set(used))}
    return envelope("render-template", data, sources=config.sources + sources, show_sensitive=args.show_sensitive, sensitive=True)


def command_vault_info(args: argparse.Namespace) -> dict[str, Any]:
    config = resolve_config(args)
    return envelope("vault-info", backend_for(config).info(), sources=config.sources)


def command_vault_init(args: argparse.Namespace) -> dict[str, Any]:
    config = resolve_config(args)
    return envelope("vault-init", {"backend": config.config.get("backend"), "would_create": not args.apply}, warnings=[] if args.apply else ["dry-run only; real KeePassXC vault creation is intentionally not automated in v1"], sources=config.sources)


def command_vault_backup(args: argparse.Namespace) -> dict[str, Any]:
    config = resolve_config(args)
    database = config.config.get("database")
    if not database:
        return envelope("vault-backup", {"database": None, "would_copy": False}, warnings=["No database path configured"], sources=config.sources)
    src = Path(str(database)).expanduser()
    if not src.is_absolute():
        src = config.repo_root / src
    target = Path(args.output).expanduser().resolve() if args.output else src.with_suffix(src.suffix + ".bak")
    if is_path_under(config.repo_root, target) and not is_ignored_path(config.repo_root, target):
        raise CliError("tracked_output_refused", f"Refusing to write vault backup to non-ignored repo path: {target}")
    if args.apply:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
    return envelope("vault-backup", {"source": str(src), "target": str(target), "would_copy": not args.apply}, warnings=[] if args.apply else ["dry-run only; pass --apply to copy"], sources=config.sources)


SCHEMAS: dict[str, dict[str, Any]] = {
    "config": {"type": "object", "required": ["backend"], "properties": {"backend": {"enum": ["keepassxc", "fake"]}, "map_path": {"type": "string"}}},
    "map": {"type": "object", "required": ["entries"], "properties": {"entries": {"type": "object"}, "aliases": {"type": "object"}}},
    "reference": {"oneOf": ["Secret ID: <id>", "{{secret:<id>:<field>}}", "secret://localsetup/<scope>/<profile>/<id>#field=<field>"]},
    "batch": {"type": "object", "required": ["items"], "properties": {"items": {"type": "array"}}},
    "command-result": {"required": ["ok", "command", "data", "warnings", "errors", "sources", "sensitive", "redactions"]},
}


def command_schema_dump(args: argparse.Namespace) -> dict[str, Any]:
    name = clean_text(args.schema, label="schema", max_len=64, required=True)
    if name not in SCHEMAS:
        raise CliError("unknown_schema", f"Unknown schema: {name}")
    return envelope("schema-dump", {"schema": name, "contract": SCHEMAS[name]})


def is_tracked_path(repo_root: Path, path: Path) -> bool:
    try:
        rel = path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return False
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(rel)],
        cwd=repo_root,
        shell=False,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    return result.returncode == 0


def is_path_under(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def is_ignored_path(repo_root: Path, path: Path) -> bool:
    try:
        rel = path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return False
    result = subprocess.run(
        ["git", "check-ignore", "-q", str(rel)],
        cwd=repo_root,
        shell=False,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    return result.returncode == 0


COMMANDS = {
    "doctor": command_doctor,
    "config-show": command_config_show,
    "config-init": command_config_init,
    "config-validate": command_config_validate,
    "map-validate": command_map_validate,
    "list": command_list,
    "search": command_search,
    "reference": command_reference,
    "resolve": command_resolve,
    "ensure": command_ensure,
    "set": command_set,
    "rotate": command_rotate,
    "delete": command_delete,
    "audit": command_audit,
    "export-env": command_export_env,
    "render-template": command_render_template,
    "vault-info": command_vault_info,
    "vault-init": command_vault_init,
    "vault-backup": command_vault_backup,
    "schema-dump": command_schema_dump,
}


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--format", choices=("json", "human"), default="json")
    parser.add_argument("--repo-root")
    parser.add_argument("--config")
    parser.add_argument("--map")
    parser.add_argument("--backend", choices=("keepassxc", "fake"))
    parser.add_argument("--profile")
    parser.add_argument("--scope")
    parser.add_argument("--database")
    parser.add_argument("--keepassxc-binary", default=None)
    parser.add_argument("--fake-store")
    parser.add_argument("--show-sensitive", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in COMMANDS:
        p = sub.add_parser(name)
        add_common(p)
        if name in {"search"}:
            p.add_argument("query")
        if name in {"reference"}:
            p.add_argument("reference")
        if name in {"resolve", "rotate", "delete"}:
            p.add_argument("id")
        if name in {"rotate", "delete"}:
            p.add_argument("--apply", action="store_true")
        if name == "resolve":
            p.add_argument("--field", default=None)
        if name == "ensure":
            p.add_argument("id", nargs="?")
            p.add_argument("--batch")
            p.add_argument("--username")
            p.add_argument("--rotate", action="store_true")
            p.add_argument("--apply", action="store_true")
        if name == "set":
            p.add_argument("id")
            p.add_argument("field")
            p.add_argument("value", nargs="?")
            p.add_argument("--stdin", action="store_true")
            p.add_argument("--apply", action="store_true")
        if name in {"config-init", "vault-init"}:
            p.add_argument("--apply", action="store_true")
        if name == "vault-backup":
            p.add_argument("--output")
            p.add_argument("--apply", action="store_true")
        if name == "export-env":
            p.add_argument("vars", nargs="+")
        if name == "render-template":
            p.add_argument("template")
            p.add_argument("--output")
            p.add_argument("--apply", action="store_true")
            p.add_argument("--allow-tracked-output", action="store_true")
            p.add_argument("--allow-unignored-output", action="store_true")
        if name == "schema-dump":
            p.add_argument("--schema", required=True, choices=sorted(SCHEMAS))
    return parser


def print_human(result: dict[str, Any]) -> None:
    print(f"{result['command']}: {'ok' if result['ok'] else 'failed'}")
    if result.get("warnings"):
        for warning in result["warnings"]:
            print(f"warning: {warning}")
    if result.get("errors"):
        for error in result["errors"]:
            print(f"error: {error.get('code')}: {error.get('message')}")
    if result.get("data") is not None:
        print(json.dumps(result["data"], indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = COMMANDS[args.command](args)
    except CliError as exc:
        result = envelope(
            args.command,
            exc.details,
            ok=False,
            errors=[{"code": exc.code, "message": clean_text(exc.message, label="error", max_len=1024)}],
        )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        result = envelope(
            args.command,
            None,
            ok=False,
            errors=[{"code": exc.__class__.__name__, "message": clean_text(str(exc), label="error", max_len=1024)}],
        )
    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print_human(result)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
