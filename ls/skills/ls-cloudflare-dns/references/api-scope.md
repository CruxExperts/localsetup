# API scope

The helper is scoped to Cloudflare v4 DNS and zone endpoints:

- `/zones`
- `/zones/{zone_id}`
- `/zones/{zone_id}/activation_check`
- `/zones/{zone_id}/settings`
- `/zones/{zone_id}/settings/{setting_id}`
- `/zones/{zone_id}/dns_settings`
- `/zones/{zone_id}/dns_records`
- `/zones/{zone_id}/dns_records/{dns_record_id}`
- `/zones/{zone_id}/dns_records/batch`
- `/zones/{zone_id}/dns_records/import`
- `/zones/{zone_id}/dns_records/export`
- `/zones/{zone_id}/dns_records/scan/trigger`
- `/zones/{zone_id}/dns_records/scan/review`

The legacy DNS scan endpoint is documentation-only. Prefer the current scan trigger, list, and review commands.

Out of direct tooling scope: DNSSEC, Registrar, Workers, Pages, WAF, Zero Trust, R2, D1, Turnstile, and account billing.
