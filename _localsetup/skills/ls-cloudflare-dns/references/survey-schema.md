# Suggested zone survey report schema

This skill does not ship `survey_dns_zones.py` or any other survey generator. Use this schema only when manually writing a survey or when a future reviewed Python helper is added.

```yaml
survey_generated_at: <ISO8601 timestamp>
this_host_ip: <public IP of the machine that ran the survey>
zones:
  - zone: <domain name>
    zone_id: <Cloudflare zone ID>
    records:
      - id: <record ID>
        type: A | CNAME | MX | TXT | ...
        name: <FQDN>
        content: <value>
        proxied: true | false
        ttl: <integer>
        points_to_this_host: true | false
```

`points_to_this_host` is `true` if the record is an A record pointing to this machine's public IP, or a CNAME whose target resolves to such an A record.

Suggested output files:
- `cloudflare_dns_survey.json`
- `cloudflare_dns_survey.yaml` if YAML output is intentionally produced

Suggested output directory: `~/.localsetup/context/dns/`

Treat these files as sensitive (they contain record IDs and content). Store in a gitignored location.
