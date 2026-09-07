"""Static sealed-runtime dependency and native capability diagnostics."""
from email.parser import Parser
import os
from pathlib import Path
import stat
import sys

from .native_bundle import _platform

LIMIT = 1024 * 1024


def _text(path: Path) -> str:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > LIMIT:
            raise ValueError('Invalid installed metadata')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(LIMIT + 1)
        if len(raw) > LIMIT:
            raise ValueError('Installed metadata exceeds bounds')
        return raw.decode('utf-8')
    finally:
        os.close(fd)


def dependencies(release: Path) -> dict:
    """Call only while the owning selected-runtime inventory lease is held."""
    try:
        from packaging.requirements import Requirement
        from packaging.utils import canonicalize_name
        from packaging.version import Version
        site = release / 'venv/lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'site-packages'
        expected = {}
        for filename in ('sdk-runtime.lock', 'sdk-build.lock'):
            raw = _text(site / 'ls/config' / filename)
            for line in raw.splitlines():
                if not line.strip() or line.lstrip().startswith(('#', '--hash=')):
                    continue
                requirement = Requirement(line.removesuffix('\\').strip())
                if requirement.url or requirement.extras:
                    raise ValueError('Unsupported installed dependency declaration')
                if requirement.marker is not None and not requirement.marker.evaluate():
                    continue
                name = canonicalize_name(requirement.name)
                if name in expected and expected[name] != requirement.specifier:
                    raise ValueError('Conflicting installed dependency declarations')
                expected[name] = requirement.specifier
        if not expected or len(expected) > 256:
            raise ValueError('Invalid dependency inventory size')
        paths = list(site.glob('*.dist-info/METADATA'))
        if len(paths) > 512:
            raise ValueError('Installed distribution inventory exceeds bounds')
        actual = {}
        for path in paths:
            metadata = Parser().parsestr(_text(path), headersonly=True)
            names, versions = metadata.get_all('Name', []), metadata.get_all('Version', [])
            if len(names) != 1 or len(versions) != 1:
                raise ValueError('Ambiguous installed distribution identity')
            name = canonicalize_name(names[0], validate=True)
            Version(versions[0])
            if name in actual:
                raise ValueError('Duplicate installed distribution')
            actual[name] = versions[0]
        missing = sorted(set(expected) - set(actual))
        mismatched = sorted(name for name in expected if name in actual and actual[name] not in expected[name])
        return {'status': 'verified' if not missing and not mismatched else 'mismatch',
                'expected_count': len(expected), 'missing': missing, 'mismatched': mismatched}
    except (ImportError, OSError, ValueError, TypeError, UnicodeError):
        return {'status': 'unavailable'}


def native(release: Path) -> dict:
    try:
        _platform()
    except ValueError:
        return {'status': 'unsupported_platform', 'execution_tested': False}
    binary = release / 'venv/lscli-native/bwrap'
    try:
        info = binary.lstat()
    except FileNotFoundError:
        return {'status': 'missing', 'execution_tested': False}
    if not stat.S_ISREG(info.st_mode) or not info.st_mode & stat.S_IXUSR:
        return {'status': 'invalid', 'execution_tested': False}
    return {'status': 'present_unprobed', 'execution_tested': False}
