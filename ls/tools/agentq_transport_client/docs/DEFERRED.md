# Deferred items (explicit)

Canonical ordered backlog: **AGENTIC_AGENT_Q_BIDIRECTIONAL_BUILD_SPEC.md** Part 19.

| Item | Reason |
|------|--------|
| PGPy decrypt of gpg-only strict blob on mail pull | If recipient decrypt fails, use gpg homedir path in mail skill or file_drop fallback |
| Google Drive / Dropbox **API** (non-sync) | OAuth + API; v1 = sync folder via StubDriveAdapter |
| Telegram **real** API | StubTelegramAdapter only; IM adapter scheduled Part 17 |

## Recently implemented (was deferred)

- Mail outer sign-then-encrypt: `preencrypted_openpgp_armored` in mail_send_encrypted; `mail_ship_strict_gpg` + CLI **ship-mail-strict**; pull accepts envelope with `manifest_version` as direct manifest.
- Multi-recipient: `to_agent_ids` in schema + manifest_validate; **ship-file-drop-multi** + `ship_file_drop_multi`.
- Formal adapter registry: **ADAPTER_REGISTRY**, **get_adapter**, StubDriveAdapter, StubTelegramAdapter.
- File lock: **claim_with_lockfile** + **file-drop-poll --use-lockfile**.
- Part 18: **ADMIN_GUIDE** expanded (rotation, conflicts, insecure rationale, force audit, automation profile).
