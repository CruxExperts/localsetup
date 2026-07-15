#!/usr/bin/env python3
# Purpose: Load and validate agent_trust_registry YAML fail-closed.
# Created: 2026-03-09
# Last updated: 2026-03-09

"""Registry: map OpenPGP fingerprint -> agent_id; list allowed roots per agent."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_ENGINE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ENGINE))
from lib.deps import check_deps, require_deps  # noqa: E402

require_deps(["yaml"])

import yaml  # noqa: E402


class RegistryError(RuntimeError):
    """Invalid or unsafe registry configuration."""


def _normalize_fp(fp: str) -> str:
    return "".join(c for c in fp.upper() if c in "0123456789ABCDEF")


def load_registry_yaml(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise RegistryError(f"Registry file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        raise RegistryError(f"Invalid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise RegistryError("Registry root must be a mapping.")
    # Minimal schema (Part 4): version, local_agent_id, agents
    for key in ("version", "local_agent_id", "agents"):
        if key not in raw:
            raise RegistryError(f"Registry missing required key: {key}")
    if raw.get("version") != 1:
        raise RegistryError("Registry version must be 1.")
    local_id = raw.get("local_agent_id")
    if not local_id or not isinstance(local_id, str):
        raise RegistryError("local_agent_id must be a non-empty string.")
    agents = raw.get("agents")
    if not isinstance(agents, dict) or not agents:
        raise RegistryError("agents must be a non-empty mapping.")
    return raw


def _collect_public_key_paths(agent_cfg: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    if "public_key_path" in agent_cfg and agent_cfg["public_key_path"]:
        paths.append(Path(agent_cfg["public_key_path"]).expanduser())
    for p in agent_cfg.get("public_keys") or []:
        if p:
            paths.append(Path(p).expanduser())
    return paths


def validate_registry(raw: dict[str, Any], *, require_keys_exist: bool = True) -> dict[str, Any]:
    """Validate registry; build fingerprint -> agent_id map. Fail closed."""
    if check_deps(["pgpy"]):
        raise RegistryError(
            "PGPy required for registry validation. Run `uv sync --locked --no-dev` "
            "or re-run the framework install script with --sync-env."
        )
    import pgpy  # type: ignore

    agents = raw["agents"]
    fp_to_agent: dict[str, str] = {}
    for agent_id, cfg in agents.items():
        if not isinstance(cfg, dict):
            raise RegistryError(f"agents.{agent_id} must be a mapping.")
        key_paths = _collect_public_key_paths(cfg)
        if not key_paths:
            raise RegistryError(f"agents.{agent_id} has no public_key_path or public_keys.")
        for kp in key_paths:
            if require_keys_exist and not kp.is_file():
                raise RegistryError(f"Public key file missing: {kp}")
            if kp.is_file():
                try:
                    key, _ = pgpy.PGPKey.from_file(str(kp))
                    fp = _normalize_fp(str(key.fingerprint))
                    if fp in fp_to_agent and fp_to_agent[fp] != agent_id:
                        raise RegistryError(f"Fingerprint collision: {fp}")
                    fp_to_agent[fp] = agent_id
                except RegistryError:
                    raise
                except Exception as exc:
                    raise RegistryError(f"Unreadable key {kp}: {exc}") from exc
        transports = cfg.get("allowed_transports") or []
        if not isinstance(transports, list):
            raise RegistryError(f"agents.{agent_id}.allowed_transports must be a list.")
    return {"raw": raw, "fp_to_agent": fp_to_agent}


def agent_id_for_fingerprint(validated: dict[str, Any], fingerprint: str) -> str | None:
    return validated["fp_to_agent"].get(_normalize_fp(fingerprint))


def assert_sender_allowed(validated: dict[str, Any], from_agent_id: str) -> None:
    """
    Fail closed: from_agent_id must be a known agents.* key (sender allowlist).
    """
    agents = validated["raw"].get("agents") or {}
    if from_agent_id not in agents:
        raise RegistryError(
            f"from_agent_id '{from_agent_id}' not in registry agents; inbound rejected."
        )


def load_pubkey_armored_for_agent(validated: dict[str, Any], agent_id: str) -> str:
    """Read first available public key armored text for agent_id."""
    agents = validated["raw"].get("agents") or {}
    cfg = agents.get(agent_id)
    if not isinstance(cfg, dict):
        raise RegistryError(f"Unknown agent_id: {agent_id}")
    paths = _collect_public_key_paths(cfg)
    for kp in paths:
        if kp.is_file():
            return kp.read_text(encoding="utf-8", errors="replace")
    raise RegistryError(f"No public key file for agent_id: {agent_id}")


def file_drop_inbound_roots(validated: dict[str, Any], agent_id: str) -> list[Path]:
    raw = validated["raw"]["agents"].get(agent_id) or {}
    fd = raw.get("file_drop") or {}
    roots = fd.get("allowed_inbound_roots") or []
    return [Path(p).expanduser() for p in roots if p]
