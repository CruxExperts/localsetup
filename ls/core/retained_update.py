"""Keep retained repository clients out of fresh adapter-path inference."""
import json
from pathlib import Path

from .client_registry import load_client_registry
from .personal_update import _build_recorded_plan


def retained_repository_plan(source: Path, home: Path, target: Path):
    receipt = target / '.localsetup/lock.json'
    if not receipt.exists():
        receipt = target / 'localsetup.lock.json'
    if not receipt.exists():return None
    lock = json.loads(receipt.read_text())
    if not isinstance(lock, dict) or lock.get('skill_scope', 'repo') != 'repo':return None
    if not retained_repository_clients(source, lock):return None
    # The existing builder validates recorded paths, health and receipt/registry hashes.
    return _build_recorded_plan(source, home, target, 'repo')


def retained_repository_clients(source: Path, lock: dict) -> list[str]:
    clients = lock.get('platforms', [])
    if not isinstance(clients, list):return []
    retained = {v.variant_id for v in load_client_registry(source).variants()
                if v.data.get('integration', {}).get('lifecycle') == 'retained-only'}
    return [client for client in clients if isinstance(client, str) and client in retained]
