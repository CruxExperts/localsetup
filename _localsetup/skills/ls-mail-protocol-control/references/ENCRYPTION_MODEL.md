# Encryption model

## Core principle

Encryption and decryption operate on a full envelope object:

- headers
- text body
- html body
- attachment metadata
- attachment content bytes

This ensures body and attachments are protected together.

## Envelope schema

```json
{
  "headers": {
    "from": "help@example.com",
    "to": "agent@example.net",
    "cc": "",
    "subject": "Secure payload"
  },
  "text_plain": "Body text",
  "text_html": "<p>Body text</p>",
  "attachments": [
    {
      "filename": "payload.bin",
      "content_type": "application/octet-stream",
      "size": 4,
      "content_bytes_base64": "AAECAwQ="
    }
  ]
}
```

## Supported modes

- `psk`: AES-GCM with HKDF key derivation from pre-shared key.
- `password`: AES-GCM with PBKDF2-derived key.
- `openpgp`: pure-Python OpenPGP encryption and decryption.

## Transport pattern

For encrypted send, the encrypted payload is serialized to JSON and sent as message body with `X-Localsetup-Encrypted` header.

## Validation and limits

- Attachment count and size limits enforced before encryption.
- Invalid base64 payloads rejected.
- Decryption fails with deterministic error codes on malformed payloads or wrong key material.

