"""Strict explicit provider configuration without credential discovery or writes."""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Profile:
    base_url: str
    api: str
    model: str
    credential_env: str
    timeout_seconds: float
    capabilities: frozenset[str]

    @property
    def endpoint(self) -> str:
        return self.base_url + ('chat/completions' if self.api == 'chat_completions' else 'responses')

    def credential(self, environment: dict[str, str]) -> str:
        value = environment.get(self.credential_env, '')
        if not value or not value.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError('Selected profile credential is missing or invalid')
        return value


def parse(value: object) -> Profile:
    required = {'base_url', 'api', 'model', 'credential_env', 'timeout_seconds', 'capabilities', 'allow_loopback_http'}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError('Provider profile fields must match schema version 1')
    base = value['base_url']
    if not isinstance(base, str) or not base.isascii() or any(ord(c) <= 32 or ord(c) == 127 for c in base):
        raise ValueError('Invalid provider base URL')
    url = urlsplit(base)
    allow = value['allow_loopback_http']
    if type(allow) is not bool or url.username is not None or url.password is not None or not url.hostname or url.query or url.fragment or '%' in base or '\\' in base:
        raise ValueError('Provider URL must not contain credentials, escapes, query or fragment')
    try:
        loopback = ipaddress.ip_address(url.hostname).is_loopback
    except ValueError:
        loopback = False
    if url.scheme != 'https' and not (url.scheme == 'http' and allow and loopback):
        raise ValueError('Provider requires HTTPS or explicitly allowed literal loopback HTTP')
    if url.port == 0 or any(part in {'.', '..'} for part in url.path.split('/')):
        raise ValueError('Provider URL must be canonical')
    if value['api'] not in ('chat_completions', 'responses'):
        raise ValueError('Unsupported provider API')
    model = value['model']
    if not isinstance(model, str) or not model or len(model) > 256 or any(ord(c) < 32 for c in model):
        raise ValueError('Explicit model identifier is required')
    credential = value['credential_env']
    if not isinstance(credential, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', credential):
        raise ValueError('Explicit credential environment variable is required')
    timeout = value['timeout_seconds']
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        raise ValueError('Provider timeout must be finite and within 3600 seconds')
    capabilities = value['capabilities']
    if not isinstance(capabilities, list) or any(not isinstance(c, str) for c in capabilities) or len(set(capabilities)) != len(capabilities) or not set(capabilities) <= {'streaming', 'tools', 'images', 'native_schema'}:
        raise ValueError('Invalid explicit provider capabilities')
    return Profile(base.rstrip('/') + '/', value['api'], model, credential, float(timeout), frozenset(capabilities))


def document(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError('Provider profiles must be an explicit regular file')
    with path.open('rb') as stream:
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError('Provider configuration exceeds 1 MiB')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate provider configuration key')
            result[key] = value
        return result
    document = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(document, dict) or set(document) != {'schema_version', 'profiles'} or type(document['schema_version']) is not int or document['schema_version'] != 1 or not isinstance(document['profiles'], dict):
        raise ValueError('Unsupported provider configuration schema')
    return document['profiles']


def load(path: Path, name: str) -> Profile:
    profiles = document(path)
    if name not in profiles:
        raise ValueError('Named provider profile does not exist')
    return parse(profiles[name])


def wire(profile: Profile) -> dict:
    """Canonical explicit profile representation used for history compatibility."""
    return {'base_url': profile.base_url, 'api': profile.api, 'model': profile.model,
            'credential_env': profile.credential_env, 'timeout_seconds': profile.timeout_seconds,
            'capabilities': sorted(profile.capabilities),
            'allow_loopback_http': profile.base_url.startswith('http://')}
