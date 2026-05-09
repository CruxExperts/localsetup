# API examples

## Tool input and output examples

### `mail_capabilities_get`

Request:

```json
{
  "acct": "support"
}
```

Response:

```json
{
  "ok": true,
  "code": "OK",
  "account_id": "support",
  "smtp": {
    "mode": "starttls",
    "features": ["auth", "size", "8bitmime"]
  },
  "imap": {
    "capabilities": ["IMAP4REV1", "MOVE", "UIDPLUS"]
  }
}
```

### `mail_query` with pagination

Request:

```json
{
  "acct": "support",
  "mailbox": "INBOX",
  "query": "UNSEEN",
  "lim": 25,
  "offset": 0
}
```

Response:

```json
{
  "ok": true,
  "code": "OK",
  "items": [
    {"id": "912", "from": "customer@example.com", "sub": "Need help", "dt": "Sat, 07 Mar 2026 20:14:11 +0000"}
  ],
  "total": 45,
  "next": 25,
  "next_actions": ["mail_get", "mail_mutate"]
}
```

### `mail_mutate` blocked by policy

Request:

```json
{
  "acct": "support",
  "mailbox": "INBOX",
  "mutate_action": "delete_mailbox",
  "target_mailbox": "Old"
}
```

Response:

```json
{
  "ok": false,
  "code": "ACTION_BLOCKED",
  "message": "policy_deny"
}
```

### `mail_mutate` confirmation challenge

Request:

```json
{
  "acct": "support",
  "mailbox": "INBOX",
  "mutate_action": "delete_messages",
  "uids": ["1", "2", "3", "4", "5"],
  "count": 5
}
```

Response:

```json
{
  "ok": false,
  "code": "CONFIRMATION_REQUIRED",
  "message": "Confirmation required. token=... expires_at=..."
}
```

Follow-up request with token:

```json
{
  "acct": "support",
  "mailbox": "INBOX",
  "mutate_action": "delete_messages",
  "uids": ["1", "2", "3", "4", "5"],
  "count": 5,
  "confirm_token": "token-from-challenge"
}
```

### `mail_send`

Request:

```json
{
  "acct": "support",
  "from": "help@example.com",
  "to": ["customer@example.com"],
  "subject": "Re: Update",
  "body": "We have applied the fix. Please confirm.",
  "attachments": [
    {
      "filename": "report.txt",
      "content_type": "text/plain",
      "content_bytes_base64": "UmVwb3J0IGRhdGE="
    }
  ]
}
```

Response:

```json
{
  "ok": true,
  "code": "OK",
  "accepted": ["customer@example.com"],
  "attachment_count": 1
}
```

### `mail_get_attachment`

Request:

```json
{
  "acct": "support",
  "mailbox": "INBOX",
  "id": "912",
  "attachment_index": 0,
  "offset": 0,
  "chunk_size": 262144
}
```

Response:

```json
{
  "ok": true,
  "code": "OK",
  "id": "912",
  "attachment_index": 0,
  "filename": "report.txt",
  "content_type": "text/plain",
  "size": 11,
  "offset": 0,
  "chunk_size": 11,
  "content_bytes_base64": "UmVwb3J0IGRhdGE=",
  "next_offset": null,
  "done": true
}
```

### `mail_encrypt`

Request:

```json
{
  "acct": "support",
  "encryption_mode": "psk",
  "from": "help@example.com",
  "to": ["agent@example.net"],
  "subject": "Secure payload",
  "body": "Confidential body text",
  "attachments": [
    {
      "filename": "payload.bin",
      "content_type": "application/octet-stream",
      "content_bytes_base64": "AAECAwQ="
    }
  ]
}
```

Response:

```json
{
  "ok": true,
  "code": "OK",
  "mode": "psk",
  "encrypted": {
    "mode": "psk",
    "ciphertext_b64": "<base64>",
    "nonce_b64": "<base64>",
    "salt_b64": "<base64>",
    "digest": "sha256"
  }
}
```

### `mail_send_encrypted`

Request:

```json
{
  "acct": "support",
  "from": "help@example.com",
  "to": ["agent@example.net"],
  "subject": "Secure transport",
  "encryption_mode": "openpgp",
  "body": "Encrypted in transport envelope"
}
```

Response:

```json
{
  "ok": true,
  "code": "OK",
  "accepted": ["agent@example.net"],
  "encryption_mode": "openpgp",
  "encrypted": {
    "mode": "openpgp"
  }
}
```

### `mail_get_decrypted`

Request:

```json
{
  "acct": "support",
  "mailbox": "INBOX",
  "id": "913",
  "encryption_mode": "password",
  "include_attachment_content": false
}
```

Response:

```json
{
  "ok": true,
  "code": "OK",
  "message": {
    "id": "913",
    "sub": "Secure transport"
  },
  "decrypted": {
    "ok": true,
    "code": "OK",
    "mode": "password",
    "envelope": {
      "headers": {"subject": "Secure transport"},
      "text_plain": "Confidential body text",
      "attachments": [
        {"filename": "payload.bin", "content_type": "application/octet-stream", "size": 4}
      ]
    }
  }
}
```

### `mail_send_encrypted` with pre-armored OpenPGP (Agent Q strict)

When `preencrypted_openpgp_armored` is set to a full armored PGP block, `encrypt_payload` is skipped and that armored string is sent as the openpgp body (no double wrap).

```json
{
  "acct": "support",
  "encryption_mode": "openpgp",
  "preencrypted_openpgp_armored": "-----BEGIN PGP MESSAGE-----\\n...",
  "from": "a@x",
  "to": ["b@x"],
  "subject": "AgentQ strict"
}
```

