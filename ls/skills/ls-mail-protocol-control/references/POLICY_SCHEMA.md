# Policy schema

## Policy file location

`ls/config/mail_protocol_policy.yaml`

## Required root keys

| Key | Type | Notes |
|---|---|---|
| `version` | integer | Start at `1` |
| `default_profile` | string | `full`, `restricted`, or `read_only` |
| `profiles` | map | Named policy profiles |
| `accounts` | map | Account-specific overrides |

## Profile schema

```yaml
profiles:
  restricted:
    allow_actions:
      - smtp.*
      - imap.read.*
      - imap.write.*
    deny_actions:
      - imap.delete_mailbox
    thresholds:
      delete_count_confirm: 50
      move_count_confirm: 100
      expunge_requires_confirm: true
      folder_delete_requires_confirm: true
```

## Validation rules

- Unknown action IDs are rejected.
- Unknown wildcard tokens are rejected.
- Wildcards expand to canonical action IDs before evaluation.
- `deny_actions` wins over `allow_actions` at the same merge level.
- Count thresholds must be integers from `0` through `1000000`.
- Confirmation booleans must be JSON/YAML booleans, not truthy strings.
- Profile and account threshold overrides are validated before startup completes.
- Invalid policy fails startup with actionable error text.
