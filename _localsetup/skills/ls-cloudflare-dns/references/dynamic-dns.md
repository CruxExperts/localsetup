# Dynamic DNS

Use `records upsert` for dynamic DNS only when the record name, zone, and target IP source are deterministic.

Recommended agent pattern:

1. Resolve public IP from a trusted source outside this skill.
2. Run `records find` for the exact `A` or `AAAA` record.
3. Emit a dry-run `records upsert`.
4. Apply only with explicit authorization or from a separate reviewed automation wrapper.

Do not schedule dynamic DNS updates from this skill alone. Use the cron orchestrator only after the exact command is reviewed, tested, and stored outside tracked secrets.
