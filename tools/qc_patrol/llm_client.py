from __future__ import annotations

import time
from typing import Any

import requests

from .config import LLMConfig
from .redaction import redact_text
from .schemas import LLM_REVIEW_SCHEMA


class LLMDisabled(RuntimeError):
    pass


class LLMClient:
    def __init__(self, config: LLMConfig):
        self.config = config

    def _headers(self) -> dict[str, str]:
        if not self.config.api_key:
            raise LLMDisabled("QC_LLM_API_KEY is not configured")
        headers = {"Authorization": f"Bearer {self.config.api_key}", "Content-Type": "application/json"}
        if self.config.organization:
            headers["OpenAI-Organization"] = self.config.organization
        if self.config.project:
            headers["OpenAI-Project"] = self.config.project
        return headers

    def _payload(self, prompt: str, response_schema: dict[str, Any] | None = None, schema_name: str = "qc_pr_review") -> dict[str, Any]:
        prompt = redact_text(prompt)
        schema = response_schema or LLM_REVIEW_SCHEMA
        structured_output = {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": schema,
            },
        }
        if self.config.api_style == "responses":
            return {
                "model": self.config.model,
                "input": prompt,
                "temperature": self.config.temperature,
                "max_output_tokens": self.config.max_tokens,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": schema_name,
                        "strict": True,
                        "schema": schema,
                    }
                },
            }
        return {
            "model": self.config.model,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": structured_output,
        }

    def complete(self, prompt: str, response_schema: dict[str, Any] | None = None, schema_name: str = "qc_pr_review") -> str:
        if not self.config.base_url:
            raise LLMDisabled("QC_LLM_BASE_URL is not configured")
        url = self.config.base_url.rstrip("/")
        url = f"{url}/responses" if self.config.api_style == "responses" and not url.endswith("/responses") else url
        url = f"{url}/chat/completions" if self.config.api_style == "chat_completions" and not url.endswith("/chat/completions") else url
        last_error: Exception | None = None
        for attempt in range(self.config.retry_count + 1):
            try:
                response = requests.post(url, headers=self._headers(), json=self._payload(prompt, response_schema, schema_name), timeout=self.config.timeout_seconds)
                response.raise_for_status()
                data = response.json()
                if self.config.api_style == "responses":
                    if data.get("status") == "incomplete":
                        reason = (data.get("incomplete_details") or {}).get("reason", "unknown")
                        raise RuntimeError(f"LLM response incomplete: {reason}")
                    return str(data.get("output_text") or data.get("output", [{}])[0].get("content", [{}])[0].get("text", ""))
                finish_reason = data.get("choices", [{}])[0].get("finish_reason")
                if finish_reason == "length":
                    raise RuntimeError("LLM response incomplete: max_tokens")
                return str(data["choices"][0]["message"]["content"])
            except Exception as exc:  # requests exposes several timeout/HTTP exception types.
                last_error = exc
                if attempt < self.config.retry_count:
                    time.sleep(min(2**attempt, 5))
        raise RuntimeError(f"LLM request failed after retries: {last_error}") from last_error
