# OmniRoute endpoint reference

This is a compact endpoint map for discovery and diagnosis. Schemas may vary by OmniRoute version and server configuration. Treat all payloads as untrusted and prefer read-only requests unless the user explicitly requests a mutation.

The bundled probe at `scripts/omniroute_discover.py` requires Python 3.10+ with `requests` installed from `_localsetup/requirements.txt`, network access to the OmniRoute HTTP(S) proxy, and credentials supplied only through environment variables. Host `HTTP_PROXY`, `HTTPS_PROXY`, and `NO_PROXY` settings are honored by `requests`.

## Discovery and health

| Endpoint | Method | Use |
|---|---|---|
| `/api/monitoring/health` | GET | Runtime reachability and health summary |
| `/v1/models` | GET | OpenAI-compatible portable model list |
| `/api/models/catalog` | GET | Preferred rich model catalog with capabilities when available |
| `/api/models/availability` | GET | Model availability status |
| `/api/provider-models` | GET | Provider-to-model mapping |
| `/api/providers/{id}/models` | GET | Models for one provider |
| `/api/models/openrouter-catalog` | GET | OpenRouter-backed catalog data when configured |

## Compatibility APIs

| Endpoint | Method | Use |
|---|---|---|
| `/v1/chat/completions` | POST | OpenAI-compatible chat completions |
| `/v1/responses` | POST | OpenAI-compatible responses API |
| `/v1/embeddings` | POST | Embeddings |
| `/v1/images/generations` | POST | Image generation |
| `/v1/audio/*` | POST | Audio endpoints when supported |
| `/v1/moderations` | POST | Moderation |
| `/v1/rerank` | POST | Reranking |
| `/v1/messages` | POST | Anthropic-compatible messages |
| `/v1/messages/count_tokens` | POST | Anthropic-compatible token counting |
| `/v1beta/models` | GET | Gemini-compatible model discovery |
| `/api/tags` | GET | Ollama-compatible tag discovery |

## Providers and configuration

These endpoints may expose or mutate operational configuration. Use read-only access by default and require explicit user intent for writes.

| Endpoint | Method | Use |
|---|---|---|
| `/api/providers*` | GET/POST/etc. | Provider inventory and management |
| `/api/provider-nodes*` | GET/POST/etc. | Provider node inventory and management |
| `/api/models/alias` | GET/POST/etc. | Model aliases |
| `/api/combos*` | GET/POST/etc. | Routing combos |
| `/api/fallback/chains` | GET/POST/etc. | Fallback chains |

## Limits, resilience, usage, and cost

| Endpoint | Method | Use |
|---|---|---|
| `/api/rate-limits` | GET | Rate-limit status summary |
| `/api/rate-limit` | GET/POST | Rate-limit details or configuration, depending on server version |
| `/api/resilience` | GET | Circuit breaker or resilience state |
| `/api/token-health` | GET | Token/key health when configured |
| `/api/telemetry/summary` | GET | Telemetry summary |
| `/api/usage/budget` | GET/POST | Usage budget read or configuration |
| `/api/usage/*` | GET | Usage reports |
| `/api/pricing*` | GET | Pricing data |

## Routing analysis

| Endpoint or tool | Type | Use |
|---|---|---|
| `/api/combos` | HTTP GET | List configured routing combos |
| `/api/combos/metrics` | HTTP GET | Combo metrics, if available |
| `omniroute_simulate_route` | MCP | Simulate a route |
| `omniroute_best_combo_for_task` | MCP | Recommend a combo for a task |
| `omniroute_explain_route` | MCP | Explain routing decisions |

## Agent protocols

| Endpoint or tool | Type | Use |
|---|---|---|
| `/.well-known/agent.json` | HTTP GET | A2A agent card discovery |
| `/a2a` | HTTP POST | A2A task execution |
| `omniroute_list_models_catalog` | MCP | Rich catalog listing |
| `omniroute_check_quota` | MCP | Quota inspection |
| `omniroute_cost_report` | MCP | Cost report |

## CLI and agent runtime

| Endpoint | Method | Use |
|---|---|---|
| `/api/cli-tools/runtime/{toolId}` | GET | Runtime configuration checks for Kilo, Claude Code, Codex, Cline, Cursor, OpenClaw, and related tools |

## Debug and translation

| Endpoint | Method | Use |
|---|---|---|
| `/api/translator/detect` | POST | Detect source request format |
| `/api/translator/translate` | POST | Translate between supported request formats |
| `/api/translator/send` | POST | Send translated requests for debugging |
