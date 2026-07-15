# Troubleshooting

Exit codes:

- `0`: command succeeded.
- `2`: local argument or validation error.
- `4`: missing or invalid local authentication setup.
- `5`: required confirmation or plan hash was missing or wrong.
- `6`: zone or upsert ambiguity.
- `8`: Cloudflare API returned an unsuccessful response.
- `130`: interrupted.

Common fixes:

- Missing token: export `CLOUDFLARE_API_TOKEN` or `CF_API_TOKEN`.
- Ambiguous zone: use the explicit zone ID.
- Apply rejected: re-run the dry-run, copy the current `plan_hash`, and use the exact confirmation phrase.
- Rate limited: inspect `rate_limit` in JSON output and retry after the indicated delay.
