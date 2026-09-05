"""Explicit OpenAI client and final-send endpoint, credential and identity guards."""
from __future__ import annotations

from contextlib import asynccontextmanager
import ssl

import httpx2 as httpx

from ..branding import user_agent
from .profiles import Profile


class BoundTransport(httpx.AsyncBaseTransport):
    def __init__(self, profile: Profile, credential: str, delegate: httpx.AsyncBaseTransport):
        self.profile, self.credential, self.delegate = profile, credential, delegate

    async def handle_async_request(self, request):
        if request.method != 'POST' or request.url != httpx.URL(self.profile.endpoint):
            raise ValueError('Request destination or method is outside the selected profile')
        content = request.content
        if len(content) > 16 * 1024 * 1024:
            raise ValueError('Serialized provider request exceeds 16 MiB')
        # Rebuild the wire headers: SDK ambient custom headers must not disclose data.
        request.headers = httpx.Headers({
            'Host': request.url.netloc.decode('ascii'), 'User-Agent': user_agent(),
            'Authorization': 'Bearer ' + self.credential, 'Content-Type': 'application/json',
            'Accept': 'application/json', 'Content-Length': str(len(content)),
        })
        return await self.delegate.handle_async_request(request)

    async def aclose(self):
        await self.delegate.aclose()


@asynccontextmanager
async def client(profile: Profile, environment: dict[str, str], *, transport=None):
    from openai import AsyncOpenAI
    credential = profile.credential(environment)
    # Explicit trust store excludes ambient proxy, CA and SDK credential settings.
    import certifi
    context = ssl.create_default_context(cafile=certifi.where())
    delegate = transport if transport is not None else httpx.AsyncHTTPTransport(verify=context, retries=0, trust_env=False)
    http = httpx.AsyncClient(transport=BoundTransport(profile, credential, delegate),
                            trust_env=False, follow_redirects=False, timeout=profile.timeout_seconds)
    sdk = AsyncOpenAI(api_key=credential, admin_api_key='', base_url=profile.base_url, organization='', project='',
                      webhook_secret='', max_retries=0, timeout=profile.timeout_seconds, http_client=http)
    # The pinned SDK merges OPENAI_CUSTOM_HEADERS during construction. Clear that
    # private adapter field before serialization as well as rebuilding wire headers.
    sdk._custom_headers = {}
    try:
        yield sdk
    finally:
        await sdk.close()

