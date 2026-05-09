# SMTP and IMAP operation matrix

| Action ID | Protocol | Category | Confirmation gate |
|---|---|---|---|
| `smtp.send_message` | SMTP | write | no |
| `smtp.send_encrypted` | SMTP | write | no |
| `smtp.verify_connectivity` | SMTP | read | no |
| `smtp.refresh_session` | SMTP | admin | no |
| `imap.list_mailboxes` | IMAP | read | no |
| `imap.query_messages` | IMAP | read | no |
| `imap.fetch_message_headers` | IMAP | read | no |
| `imap.fetch_message_body` | IMAP | read | no |
| `imap.fetch_attachment_metadata` | IMAP | read | no |
| `imap.fetch_attachment_content` | IMAP | read | no |
| `imap.fetch_and_decrypt` | IMAP | read | no |
| `imap.sync_state` | IMAP | read | no |
| `imap.get_capabilities` | IMAP | read | no |
| `imap.set_flags` | IMAP | write | no |
| `imap.clear_flags` | IMAP | write | no |
| `imap.copy_messages` | IMAP | write | no |
| `imap.move_messages` | IMAP | write | threshold |
| `imap.create_mailbox` | IMAP | write | no |
| `imap.rename_mailbox` | IMAP | write | no |
| `imap.delete_messages` | IMAP | destructive | threshold |
| `imap.expunge_mailbox` | IMAP | destructive | threshold |
| `imap.delete_mailbox` | IMAP | destructive | threshold |
| `imap.refresh_session` | IMAP | admin | no |
| `crypto.encrypt_payload` | Crypto | write | no |
| `crypto.decrypt_payload` | Crypto | read | no |

## IMAP move fallback

When server `MOVE` capability is missing:

1. `UID COPY`
2. `UID STORE +FLAGS (\Deleted)`
3. `EXPUNGE`

