# Record types

Common low-risk record types: `A`, `AAAA`, `CNAME`, `TXT`.

High-risk record types: `NS`, `MX`, `SRV`, `CAA`, `DS`, `DNSKEY`, `SVCB`, and `HTTPS`.

Notes:

- `A` and `AAAA` content is locally validated as an IP address.
- `TTL` value `1` means automatic TTL in Cloudflare.
- Proxy eligibility depends on Cloudflare product rules and record type.
- Avoid changing apex `NS`, mail routing, and certificate authority records without an explicit rollback plan.
