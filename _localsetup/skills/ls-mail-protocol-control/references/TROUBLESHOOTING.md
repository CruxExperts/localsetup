# Troubleshooting

## Failure codes and likely causes

| Code | Meaning | Fix |
|---|---|---|
| `ACCOUNT_NOT_FOUND` | Unknown account id | Verify `mail_accounts.json` |
| `CREDENTIAL_NOT_FOUND` | Missing auth value | Export required environment variables |
| `AUTH_FAILED` | SMTP or IMAP login rejected | Verify credentials and auth mode |
| `TLS_NEGOTIATION_FAILED` | STARTTLS failed | Check server TLS support and port |
| `ACTION_BLOCKED` | Policy denied action | Review `allow_actions` and `deny_actions` |
| `CONFIRMATION_REQUIRED` | Action crossed threshold | Re-run with issued confirmation token |
| `CONFIRMATION_EXPIRED` | Token timed out | Re-run and use fresh token |
| `CONFIRMATION_REPLAY_BLOCKED` | Token reused | Re-run and use fresh token |
| `INVALID_ARGUMENT` | Required fields missing or malformed | Validate request payload |
| `ATTACHMENT_INVALID_BASE64` | Attachment payload not valid base64 | Re-encode binary payload and retry |
| `ATTACHMENT_TOO_LARGE` | Single attachment exceeds limit | Reduce size or increase policy limit |
| `ATTACHMENT_TOTAL_TOO_LARGE` | Combined attachments exceed limit | Split message or increase aggregate limit |
| `ATTACHMENT_NOT_FOUND` | Attachment index not available | Refresh metadata and verify index |
| `ENCRYPTION_MODE_UNSUPPORTED` | Mode not allowed or dependency missing | Verify policy mode allowlist and dependencies |
| `KEY_MATERIAL_NOT_FOUND` | Missing crypto key material | Set required env variables |
| `DECRYPTION_FAILED` | Wrong key or malformed encrypted payload | Verify mode, key ref, and payload integrity |

## Quick diagnostic checks

1. Validate policy file structure.
2. Validate account definitions.
3. Check SMTP and IMAP capability call for one account.
4. Run a safe query action before testing mutation actions.
5. Run a controlled encrypt and decrypt round-trip before production rollout.

## Recovery playbook for failed destructive actions

1. Stop further destructive calls.
2. Switch account profile to read-only.
3. Verify mailbox state from `mail_query` and `mail_get`.
4. Execute rollback or reconciliation actions manually with explicit approvals.

