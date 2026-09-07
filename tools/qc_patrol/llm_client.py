from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any
import uuid

from .config import LLMConfig
from .redaction import redact_text
from .schemas import LLM_REVIEW_SCHEMA


class LLMDisabled(RuntimeError):
    pass


class LLMClient:
    """Keep QC's string-returning interface over protected tool-free completion."""
    def __init__(self, config: LLMConfig):
        self.config = config

    def complete(self, prompt: str, response_schema: dict[str, Any] | None = None, schema_name: str = "qc_pr_review") -> str:
        if not self.config.base_url or not self.config.api_key:
            raise LLMDisabled("QC LLM endpoint and credential must be configured")
        try:
            from ls.core.agent.completion_run import run,identity
            from ls.core.agent.coding_run import CodingGrant
            from ls.core.agent.profiles import parse,wire
            from ls.core.agent.diagnostics import locations
            base=self.config.base_url.rstrip('/')
            suffix='/responses' if self.config.api_style=='responses' else '/chat/completions'
            if base.endswith(suffix):base=base[:-len(suffix)]
            capabilities=['native_schema']+['reasoning:'+effort for effort in self.config.reasoning_efforts]
            if self.config.temperature_supported:capabilities.append('temperature')
            elif self.config.temperature!=0:raise ValueError('Temperature requires explicit support')
            profile=parse({'base_url':base,'api':self.config.api_style,'model':self.config.model,
                'credential_env':'QC_LLM_API_KEY','timeout_seconds':self.config.timeout_seconds,
                'capabilities':capabilities,'allow_loopback_http':self.config.allow_loopback_http,
                'organization':self.config.organization,'project':self.config.project})
            request={'interface_version':1,'model':profile.model,'deadline_seconds':self.config.timeout_seconds,
                'max_attempts':1,'max_output_tokens':self.config.max_tokens,'input':redact_text(prompt),
                'output_schema':response_schema if response_schema is not None else LLM_REVIEW_SCHEMA,'schema_name':schema_name}
            if self.config.reasoning_effort:request['reasoning_effort']=self.config.reasoning_effort
            if self.config.temperature_supported:request['temperature']=self.config.temperature
            payload={'profile':wire(profile),'credential':self.config.api_key,'request':json.dumps(request,allow_nan=False)}
            identifier=uuid.uuid4().hex
            authority=CodingGrant(identifier,identifier,identity(payload),time.monotonic()+self.config.timeout_seconds)
            root=Path(self.config.runtime_root or locations(Path.home())['runtimes']).expanduser().absolute()
            result=run(root,payload,authority)
        except TimeoutError:raise RuntimeError('QC completion deadline') from None
        except (OSError,ValueError,TypeError,RuntimeError,ImportError):raise RuntimeError('QC completion unavailable or uncertain') from None
        if result['status']=='unavailable':raise LLMDisabled('QC completion unavailable')
        if result['status']!='succeeded':raise RuntimeError('QC completion '+result['status'])
        return json.dumps(result['data'],ensure_ascii=True,separators=(',',':'),allow_nan=False)
