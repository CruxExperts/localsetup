"""Resolve repository detach authority from installation receipts."""
from pathlib import Path
from .installation_ownership import InstallationOwner


def recorded_detach_rows(lock: dict, target: Path):
    rows = lock.get('adapter_targets', [])
    if not isinstance(rows, list):raise ValueError('Invalid recorded adapter targets')
    result = [];seen = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('path'), str):
            raise ValueError('Invalid recorded adapter target')
        path = Path(row['path'])
        if not path.is_absolute():path = target / path
        if '..' in path.parts:raise ValueError('Unsafe recorded adapter path')
        try:path.parent.resolve().relative_to(target.resolve())
        except ValueError:raise ValueError('Recorded adapter escapes target') from None
        if path == target or str(path) in seen:raise ValueError('Duplicate or invalid recorded adapter path')
        seen.add(str(path))
        if 'owners' in row:
            if not isinstance(row['owners'], list):raise ValueError('Invalid recorded adapter owners')
            owners = [InstallationOwner(**raw) for raw in row['owners']]
            if any(o.scope != 'repo' or o.root != str(target.resolve()) for o in owners):
                raise ValueError('Recorded repository owner does not match target')
            clients = {o.client for o in owners}
        else:
            values = row['platforms'] if 'platforms' in row else ([row['platform']] if row.get('platform') else [])
            if not isinstance(values, list) or any(not isinstance(c, str) or not c for c in values):
                raise ValueError('Invalid recorded adapter clients')
            clients = set(values)
        result.append((path, row, clients))
    return result
