"""Worker-only SDK model construction over the shared explicit transport."""
from __future__ import annotations

from contextlib import asynccontextmanager
import sys

from .profiles import Profile
from .provider_client import client
from .sdk_imports import PayloadFinder


@asynccontextmanager
async def model(profile: Profile, environment: dict[str, str], finder: PayloadFinder, *, transport=None, response_guard=None):
    if not sys.flags.isolated or not sys.dont_write_bytecode or sys.meta_path[0] is not finder:
        raise RuntimeError('SDK models require the active isolated worker importer')
    finder.verify_origins()
    from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
    from pydantic_ai.providers.openai import OpenAIProvider
    from pydantic_ai.profiles import DEFAULT_PROFILE
    finder.verify_origins()
    capabilities = {
        'supports_tools': 'tools' in profile.capabilities,
        'supports_json_schema_output': 'native_schema' in profile.capabilities,
        'supports_json_object_output': False,
        'supported_native_tools': frozenset(),
    }
    async with client(profile, environment, transport=transport, response_guard=response_guard) as sdk:
        provider = OpenAIProvider(openai_client=sdk)
        from .sdk_response_stream import guarded_type
        adapter = OpenAIChatModel if profile.api == 'chat_completions' else guarded_type(OpenAIResponsesModel)
        instance = adapter(profile.model, provider=provider, profile=lambda inferred: {**DEFAULT_PROFILE, **capabilities})
        finder.verify_origins()
        try:
            yield instance
        finally:
            finder.verify_origins()
