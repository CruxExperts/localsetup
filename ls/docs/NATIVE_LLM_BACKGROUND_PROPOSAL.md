---
status: PROPOSAL
version: 4.4
---

# Native LLM completion interface for background consumers

Status: **PROPOSED**. Maintenance handoff; no runtime enhancement is implemented by this document.

## Purpose and boundary

Provide one supported, installed `localsetup llm complete` interface for bounded,
tool-free structured API requests. FleetOps needs exception interpretation while
its deterministic documentation worker continues independently. Extend the
existing HTTP client; do not introduce agent CLI routing, provider discovery,
tools, autonomous execution, a scheduler, or a general agent runtime.

## Verified baseline

Inspected upstream `main` at `1e03acd5a3bb339709cc8edc2596948674f73542`.
The relevant owners are `tools/qc_patrol/llm_client.py`,
`tools/qc_patrol/config.py`, and `pyproject.toml`.

- `LLMConfig` has no reasoning-effort field; neither API payload transmits effort.
- Responses parsing checks only the first output item's first content item when
  top-level `output_text` is absent. A reasoning-first response returns empty text.
- The broad exception handler retries missing credentials even though no HTTP
  request was dispatched. It also retries ambiguous transport failures.
- Package discovery includes `ls*`; the client under `tools/qc_patrol` is not a
  supported installed consumer interface.
- `complete` returns only text, without normalized status, usage or request ID.
- `jsonschema` and `requests` are existing runtime dependencies. Reuse them.

The [OpenAI reasoning guide](https://developers.openai.com/api/docs/guides/reasoning)
describes reasoning output alongside message output. Consumers must inspect
relevant output items rather than assume item zero contains the answer.

## Synthetic reproductions

Run from the source checkout with its locked Python environment. This fixture
uses no credentials, network calls or live model requests.

```python
from types import SimpleNamespace
from unittest.mock import Mock, patch
from tools.qc_patrol.llm_client import LLMClient

config = SimpleNamespace(
    base_url="https://provider.invalid/v1", api_key="fixture-only",
    model="fixture-model", temperature=0, max_tokens=100,
    timeout_seconds=1, retry_count=1, api_style="responses",
    organization="", project="", reasoning_effort="high",
)
client = LLMClient(config)
assert "reasoning" not in client._payload("fixture")
response = Mock()
response.json.return_value = {
    "status": "completed",
    "output": [
        {"type": "reasoning", "summary": []},
        {"type": "message", "content": [
            {"type": "output_text", "text": '{"ok":true}'}
        ]},
    ],
}
with patch("tools.qc_patrol.llm_client.requests.post", return_value=response):
    assert client.complete("fixture") == ""
config.api_key = ""
with patch("tools.qc_patrol.llm_client.requests.post") as post, \
     patch("tools.qc_patrol.llm_client.time.sleep") as sleep:
    try:
        client.complete("fixture")
    except RuntimeError:
        pass
    assert post.call_count == 0
    assert sleep.call_count == 1
```

These assertions reproduce current defects. Future implementation tests should
assert the corrected behavior instead of retaining those defects as requirements.

## Requested interface

`localsetup llm complete --profile <private-profile> --request <file-or-dash>`
accepts a sanitized JSON request through a file or stdin. The named private
profile owns credentials, endpoint, API style and supported optional parameters.
The request selects an explicit model, reasoning effort, output schema, overall
deadline, maximum attempts and output token limit. Standard output contains one
versioned JSON envelope; standard error must not expose credentials, raw provider
bodies, prompts or diagnostics. No interactive authentication or login is allowed.

Proposed request fields:

```json
{
  "interface_version": 1,
  "model": "fixture-model",
  "reasoning_effort": "high",
  "deadline_seconds": 300,
  "max_attempts": 1,
  "max_output_tokens": 8192,
  "input": {"evidence_id": "fixture-evidence", "facts": []},
  "output_schema": {
    "type": "object",
    "additionalProperties": false,
    "required": ["ok"],
    "properties": {"ok": {"type": "boolean"}}
  }
}
```

Return `interface_version`, normalized `status`, validated `data` or null,
`model`, available `usage`, provider `request_id` or null, attempts and a bounded
non-sensitive reason code. Distinguish succeeded, refused, incomplete, malformed
JSON, schema rejection, unavailable credentials, rate limited, transport failed
before dispatch, and uncertain delivery. Document exit codes for each class.

Normalize both supported existing API styles. Explicitly send reasoning effort
in the appropriate supported field. Parse all message/output-text items. Omit
optional parameters unless configured and supported; do not always send
`temperature`. Preserve existing QC callers with a compatibility wrapper around
the shared installed implementation.

Retry only classified retryable failures within both an attempt bound and a total
deadline. Missing credentials and schema/refusal errors are not transient.
Respect a bounded Retry-After for rate limits. A transport interruption after
possible provider acceptance returns uncertainty and is not automatically replayed.
The deadline includes attempts, backoff and response handling.

## Acceptance fixtures

All provider responses are synthetic and are exercised without network access.
The output schema above is shared by these fixtures.

| Case | Input fixture | Required result |
| --- | --- | --- |
| Reasoning-first | `{"status":"completed","output":[{"type":"reasoning","summary":[]},{"type":"message","content":[{"type":"output_text","text":"{\"ok\":true}"}]}]}` | succeeded; data is `{"ok":true}` |
| Multiple message items | Two output-text items whose combined text is valid JSON | all relevant text parsed in documented order |
| Refusal | `{"output":[{"type":"message","content":[{"type":"refusal","refusal":"fixture"}]}]}` | refused; no data; no retry |
| Truncation | `{"status":"incomplete","incomplete_details":{"reason":"max_output_tokens"}}` | incomplete; no retry |
| Missing credentials | Empty profile credential, counting HTTP mock | unavailable; zero HTTP calls and zero sleeps |
| Rate limit | HTTP 429, Retry-After 1, then success | bounded retry only when configured and within deadline |
| Excessive backoff | HTTP 429, Retry-After beyond total deadline | rate limited; no over-deadline sleep |
| Transport interruption | Read timeout after mocked dispatch | uncertain; one dispatch |
| Malformed JSON | Output text `{` | malformed; no data or retry |
| Schema rejection | Output text `{"ok":"yes"}` | schema rejection via existing jsonschema dependency |
| Usage extraction | Success with `usage:{"input_tokens":7,"output_tokens":3,"total_tokens":10}` and `x-request-id: fixture-request` | normalized usage and request ID retained |
| Optional parameters | Profile lacks temperature support | temperature omitted |
| Installed package | Build/install existing package in isolated environment, invoke outside source checkout | completion interface imports and runs with mocked HTTP |
| QC compatibility | Existing QC fixtures for both API styles | wrapper retains caller behavior and schema defaults |

## FleetOps consumer policy

Role `server_context_reviewer`, model `gpt-5.6-luna`, effort `high`. Input is
sanitized exception evidence. Output is interpretation, uncertainty, supplied
evidence references and supported observation suggestions. The role cannot
execute commands, change facts, write Git or delegate.

Default consumer limits: one concurrent request, five-minute deadline, 64 KiB
input, 8,192 output tokens and twenty requests per UTC day. Cache by evidence,
role, schema and model-policy revision. Routine changes make no model calls.
Unavailable service, exhausted budget, refusal and invalid output leave review
pending; deterministic documents continue. FleetOps integration remains disabled
until the supported interface is implemented, installed and verified.

This handoff is a draft for maintenance review. It does not request auto-merge,
bot dispatch, heartbeat changes or a live FleetOps rollout.
