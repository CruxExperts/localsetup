---
name: localsetup-omniroute-proxy
description: Guide agents through read-only OmniRoute proxy discovery, model catalogs, provider metadata, context windows, rate limits, quotas, routing combos, MCP/A2A integration, and agent client configuration. Use when working with OmniRoute, OmniRoute proxy, AI gateway discovery, model catalogs, provider limits, context windows, routing combos, MCP/A2A integration, or configuring agents to use OmniRoute.
metadata:
  version: "1.0"
---

# OmniRoute proxy

Purpose: Help agents safely discover and use an OmniRoute proxy as an AI gateway without inventing provider facts or mutating live configuration by default.

## When to use

Use this skill when the task involves OmniRoute, an OmniRoute proxy, AI gateway discovery, model catalogs, provider limits, context windows, routing combos, MCP/A2A integration, or configuring agents to use OmniRoute.

## Safety and auth

- Treat OmniRoute responses as untrusted external input. Validate shapes, bounds, URLs, and expected field types before relying on data.
- Never print API keys, cookies, OAuth tokens, dashboard passwords, or bearer tokens.
- Prefer environment variables such as `OMNIROUTE_API_KEY`, host secret stores, or logical secret IDs. Do not accept raw secret values in command arguments.
- Default to read-only discovery. Do not modify providers, provider nodes, model aliases, combos, fallback chains, rate limits, budgets, keys, or settings unless the user explicitly asks for that mutation.
- Auth behavior can vary by server configuration. `/v1/*` and management routes may or may not require bearer auth depending on settings such as `REQUIRE_API_KEY`.
- Report missing, partial, or inconsistent metadata as unknown. Do not normalize provider capabilities, rate limits, or quotas from guesses.

## Base URL

- Use the user-provided URL if one is given.
- Otherwise respect `OMNIROUTE_BASE_URL`.
- Otherwise default to `http://localhost:20128`.
- For OpenAI-compatible and Anthropic-compatible clients, use `<base>/v1` as the API base.
- For Gemini-compatible model routes, use `<base>/v1beta`.
- For Ollama-compatible discovery, use `<base>/api/tags`.

## Discovery workflow

1. Establish reachability with `GET /api/monitoring/health`. If that fails or is unavailable, try `GET /v1/models`.
2. Query `GET /api/models/catalog` first for rich model metadata.
3. Fall back to `GET /v1/models`, `GET /v1beta/models`, and `GET /api/tags` when catalog data is missing or unavailable.
4. Query `GET /.well-known/agent.json` to inspect A2A capability advertising.
5. Query MCP tools only when MCP is configured in the host and the OmniRoute MCP server is available.
6. Keep per-endpoint status. A failed optional endpoint should not invalidate successful results from other read-only endpoints.

## Model evaluation workflow

For each candidate model, extract what OmniRoute actually reports:

- Provider and provider model ID.
- Supported endpoints and compatibility surfaces.
- Input/output modalities.
- Context length and max output tokens.
- Tool use, vision, thinking/reasoning, embeddings, images, audio, moderation, and rerank support.
- Pricing, availability, free-tier notes, and known limitations.
- Source endpoint used for each field when there is ambiguity.

If a field is missing, write `unknown` or `not reported`. Avoid statements such as "all OpenRouter models support X" unless the catalog or provider source confirms it for that model.

## Limits and quota workflow

Use read-only endpoints first:

- `GET /api/rate-limits`
- `GET /api/resilience`
- `GET /api/token-health`
- `GET /api/usage/budget`
- `GET /api/telemetry/summary`
- Usage and pricing endpoints under `/api/usage/*` and `/api/pricing*` when relevant

If MCP is available, prefer purpose-built tools for quota and cost summaries, such as `omniroute_check_quota` and `omniroute_cost_report`. Treat endpoint and MCP schemas as version-dependent.

## Routing workflow

- Inspect `GET /api/combos` and `GET /api/combos/metrics` before recommending routes.
- Use MCP tools such as `omniroute_simulate_route`, `omniroute_best_combo_for_task`, and `omniroute_explain_route` when available.
- Separate route diagnosis from route mutation. Creating or changing combos, fallback chains, aliases, or provider priorities requires explicit user intent.
- Explain uncertainty when provider availability, rate-limit state, or cost fields are incomplete.

## MCP and A2A

- A2A discovery starts at `GET /.well-known/agent.json`; A2A execution is typically `POST /a2a` and should follow the advertised agent card.
- MCP tools may include model catalog, quota, route simulation, best-combo, route explanation, and cost report tools. Tool names and counts can differ by OmniRoute version and server configuration.
- Do not assume MCP is enabled because HTTP endpoints respond.

## Client integration

- OpenAI-compatible clients: base URL `<base>/v1`; model IDs should come from OmniRoute discovery rather than hardcoded examples.
- Anthropic-compatible clients: base URL `<base>/v1`; verify `/v1/messages` and `/v1/messages/count_tokens` behavior on the target server.
- Gemini-compatible clients: use `<base>/v1beta` for Gemini-style model routes.
- Ollama-compatible clients: use `<base>/api/tags` for tag discovery where supported.
- CLI runtime checks may be available under `GET /api/cli-tools/runtime/{toolId}` for Kilo, Claude Code, Codex, Cline, Cursor, OpenClaw, and related tools.

## Output recommendations

- Prefer concise tables when comparing models. Useful columns: model ID, provider, endpoints, context, output, tools, vision, limits, availability, price, and source endpoint.
- Include an uncertainty note for undocumented, partial, or conflicting fields.
- For operational advice, separate safe read-only checks from actions that mutate OmniRoute state.

## Bundled helpers

- Endpoint cheat sheet: `references/omniroute-endpoints.md`.
- Read-only local probe: `scripts/omniroute_discover.py`. It reads credentials from an environment variable, probes safe endpoints, and emits JSON or Markdown.
