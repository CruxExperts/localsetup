# Source ledger

Last source review: 2026-05-12.

Primary sources used for this rewrite:

- Cloudflare API calls, base URL, and token verification docs.
- Cloudflare API token permissions and rate limit docs.
- Cloudflare Zones, DNS records, DNS settings, batch, import/export, scan, TTL, record attributes, proxy limitations, and zone status docs.
- Cloudflare OpenAPI schema repository.
- Official Cloudflare SDK and agent-context repositories for ecosystem comparison only.

Source priority:

1. Cloudflare OpenAPI schema and Cloudflare API reference for endpoint paths and payload shape.
2. Cloudflare DNS product docs for operational guidance and record behavior.
3. Official SDK and MCP repositories for ecosystem context only.
4. Live authenticated behavior only when a token and safe test zone are available.

Live behavior not confirmed in this rewrite unless the validation ledger says otherwise. Do not claim live mutation behavior is verified from unit tests alone.
