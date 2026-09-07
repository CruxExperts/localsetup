"""Check declared integration lifecycle separately from qualification results."""
from pathlib import PurePosixPath
from urllib.parse import urlparse


def integration_issues(variant: dict, *, field: str) -> list[str]:
    integration = variant.get('integration')
    if integration is None:return []  # Older records await their owning revalidation.
    issues = []
    qualification = integration['qualification']
    prefix = f'{field}.integration'
    if integration['lifecycle'] != 'active' and variant.get('compatibility') is not None:
        issues.append(f'{prefix}: retained-only or unsupported clients cannot project fresh-install adapters')
    kinds = set()
    for evidence in qualification['evidence']:
        reference = evidence['reference']
        parsed = urlparse(reference)
        if parsed.scheme:
            valid = parsed.scheme == 'https' and bool(parsed.netloc) and not parsed.username and not parsed.password
        else:
            path = PurePosixPath(reference)
            valid = (not path.is_absolute() and '\\' not in reference and ':' not in reference
                     and all(not part.startswith('.') for part in path.parts)
                     and path.parts and path.parts[0] not in {'state', 'data', 'docs', 'graphify-out'})
        if not valid:
            issues.append(f'{prefix}: evidence requires a public repository path or HTTPS reference')
        else:kinds.add(evidence['kind'])
    for surface in ('filesystem', 'host'):
        if qualification[surface] == 'verified' and surface not in kinds:
            issues.append(f'{prefix}: verified {surface} qualification requires matching evidence')
    if (qualification['catalog'] == 'bounded' or qualification['host'] == 'blocked'
            or integration['lifecycle'] != 'active') and not integration['limitations']:
        issues.append(f'{prefix}: bounded, blocked, or retained status requires limitations')
    return issues
