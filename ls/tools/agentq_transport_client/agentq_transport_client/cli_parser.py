from __future__ import annotations

import argparse

from agentq_transport_client.cli_commands import (
    cmd_archive_prune,
    cmd_doctor,
    cmd_file_drop_poll,
    cmd_ingest_blob,
    cmd_key_export,
    cmd_key_fingerprint,
    cmd_key_gen,
    cmd_key_import,
    cmd_mail_move_retry,
    cmd_mail_pull,
    cmd_prune_processed,
    cmd_queue_pending,
    cmd_registry_validate,
    cmd_ship_bundle,
    cmd_ship_file_drop,
    cmd_ship_file_drop_multi,
    cmd_ship_mail,
    cmd_ship_mail_strict,
    cmd_stamp_prd,
    cmd_version,
)


def main() -> int:
    p = argparse.ArgumentParser(prog="agentq", description="Agent Q transport client CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("version", help="Print framework VERSION and optional git hash")
    sp.set_defaults(run=cmd_version)

    sp = sub.add_parser("stamp-prd", help="Stamp PRD front matter with framework version")
    sp.add_argument("path", help="Path to PRD markdown file")
    sp.add_argument("--hash", action="store_true", help="Also set localsetup_framework_hash if git available")
    sp.set_defaults(run=cmd_stamp_prd)

    sp = sub.add_parser("key-fingerprint", help="Print OpenPGP fingerprint from .asc file (needs PGPy)")
    sp.add_argument("path", help="Path to armored public key file")
    sp.set_defaults(run=cmd_key_fingerprint)

    sp = sub.add_parser("key-gen", help="Generate AgentQ OpenPGP keypair via gpg (temp homedir)")
    sp.add_argument("output", help="Output directory for agentq.pub.asc and agentq.sec.asc")
    sp.set_defaults(run=cmd_key_gen)

    sp = sub.add_parser("registry-validate", help="Validate agent_trust_registry.yaml fail-closed")
    sp.add_argument("path", help="Path to registry YAML")
    sp.add_argument("--skip-keys", action="store_true", help="Do not require key files on disk")
    sp.set_defaults(run=cmd_registry_validate)

    sp = sub.add_parser("mail-pull", help="IMAP UNSEEN -> get_decrypted -> promote -> move processed")
    sp.add_argument("--queue", required=True, help="Queue root")
    sp.add_argument("--account", required=True, help="Mail account_id")
    sp.add_argument("--policy", default="ls/config/mail_protocol_policy.yaml")
    sp.add_argument("--accounts", default="ls/config/mail_accounts.json")
    sp.add_argument("--mailbox", default="INBOX")
    sp.add_argument("--post-mailbox", default="LocalsetupAgentQ/Processed")
    sp.add_argument("--query", default="UNSEEN")
    sp.add_argument("--lim", type=int, default=25)
    sp.add_argument("--confirm-token", default="", help="If policy requires confirmation for move")
    sp.add_argument("--registry", default="", help="agent_trust_registry.yaml path; enforce from_agent_id in agents")
    sp.set_defaults(run=cmd_mail_pull)

    sp = sub.add_parser("ship-file-drop", help="Seal manifest to recipient pubkey; write .agentq.asc + .ready")
    sp.add_argument("--manifest", help="Path to PRD .md or manifest .json")
    sp.add_argument("--manifest-json", default="", help="Inline JSON manifest if no --manifest")
    sp.add_argument("--pubkey", required=True, help="Recipient public key armored file")
    sp.add_argument("--out", required=True, help="Outbound directory (allowed_outbound_roots)")
    sp.add_argument("--stem", default="payload")
    sp.add_argument("--queue", default="", help="Queue root to append out/.ship_log.jsonl")
    sp.add_argument("--skip-pre-ship", action="store_true", help="Skip manifest pre_ship_checks")
    sp.add_argument("--pre-ship-cwd", default="", help="Working dir for pre_ship_checks")
    sp.add_argument(
        "--signer-gnupghome",
        default="",
        help="If set, gpg sign-then-encrypt outer (recipient ingest uses --strict-gpg)",
    )
    sp.add_argument("--signer-uid", default="", help="Key id/email for gpg --local-user")
    sp.add_argument("--signer-passphrase", default="", help="Signer key passphrase if needed")
    sp.add_argument(
        "--write-ready-sha256",
        action="store_true",
        help="Write .ready first line sha256 <hex> matching sealed file",
    )
    sp.set_defaults(run=cmd_ship_file_drop)

    sp = sub.add_parser(
        "mail-move-retry",
        help="Retry IMAP move for ledger pending_processed_move records",
    )
    sp.add_argument("--queue", required=True)
    sp.add_argument("--account", required=True)
    sp.add_argument("--policy", default="ls/config/mail_protocol_policy.yaml")
    sp.add_argument("--accounts", default="ls/config/mail_accounts.json")
    sp.add_argument("--confirm-token", default="")
    sp.set_defaults(run=cmd_mail_move_retry)

    sp = sub.add_parser(
        "archive-prune",
        help="Prune queue archive/ by age and/or max total size",
    )
    sp.add_argument("archive_root", help="Path to archive directory")
    sp.add_argument("--days", type=float, default=0, help="Delete dirs older than N days (0=skip)")
    sp.add_argument("--max-gb", type=float, default=0, help="Trim oldest until under N GB (0=skip)")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(run=cmd_archive_prune)

    sp = sub.add_parser(
        "queue-pending",
        help="List in/ or move to pending/ (by ack_required or --transport-id)",
    )
    sp.add_argument("--queue", required=True)
    sp.add_argument("--list", action="store_true", dest="list_only", help="List in/* only")
    sp.add_argument("--transport-id", default="", help="Move single in/<id> to pending/")
    sp.set_defaults(run=cmd_queue_pending)

    sp = sub.add_parser("ship-mail", help="mail_send_encrypted agentq_outer (set openpgp_public_key in env)")
    sp.add_argument("--account", required=True)
    sp.add_argument("--from-addr", required=True, dest="from_addr")
    sp.add_argument("--to", required=True)
    sp.add_argument("--subject", default="AgentQ handoff")
    sp.add_argument("--manifest", help="Path to PRD .md or manifest .json")
    sp.add_argument("--manifest-json", default="{}")
    sp.add_argument("--policy", default="ls/config/mail_protocol_policy.yaml")
    sp.add_argument("--accounts", default="ls/config/mail_accounts.json")
    sp.add_argument("--queue", default="", help="Queue root for ship_mail_ok/fail log")
    sp.add_argument("--skip-pre-ship", action="store_true")
    sp.add_argument("--pre-ship-cwd", default="")
    sp.set_defaults(run=cmd_ship_mail)

    sp = sub.add_parser(
        "ship-mail-strict",
        help="Gpg sign-then-encrypt manifest; send as preencrypted OpenPGP (mail skill bypass)",
    )
    sp.add_argument("--account", required=True)
    sp.add_argument("--from-addr", required=True, dest="from_addr")
    sp.add_argument("--to", required=True)
    sp.add_argument("--subject", default="AgentQ handoff strict")
    sp.add_argument("--manifest", help="Path to manifest .json (to_agent_ids not used)")
    sp.add_argument("--manifest-json", default="{}")
    sp.add_argument("--pubkey", required=True, help="Recipient armored pubkey file")
    sp.add_argument("--signer-gnupghome", required=True)
    sp.add_argument("--signer-uid", default="")
    sp.add_argument("--signer-passphrase", default="")
    sp.add_argument("--policy", default="ls/config/mail_protocol_policy.yaml")
    sp.add_argument("--accounts", default="ls/config/mail_accounts.json")
    sp.add_argument("--queue", default="")
    sp.add_argument("--skip-pre-ship", action="store_true")
    sp.add_argument("--pre-ship-cwd", default="")
    sp.set_defaults(run=cmd_ship_mail_strict)

    sp = sub.add_parser("ingest-blob", help="Decrypt armored blob file and promote to queue in/")
    sp.add_argument("blob", help="Path to .agentq.asc file")
    sp.add_argument("--queue", required=True, help="Queue root (structured layout)")
    sp.add_argument("--privkey", required=True, help="Recipient secret key armored file")
    sp.add_argument("--passphrase", default="", help="Secret key passphrase")
    sp.add_argument("--extension", default=".agentq.asc", help="Sealed extension (for ready name)")
    sp.add_argument("--force", action="store_true", help="Force re-ingest even if ledger has id")
    sp.add_argument("--operator", default="", help="Operator id for ledger when --force")
    sp.add_argument("--reason", default="", help="Reason when --force")
    sp.add_argument("--registry", default="", help="Enforce from_agent_id in registry agents")
    sp.add_argument(
        "--strict-gpg",
        action="store_true",
        help="Decrypt via gpg and require Good signature bound to from_agent_id",
    )
    sp.add_argument(
        "--recipient-gnupghome",
        default="",
        help="Decrypt using this keyring (avoids armored sec import); use with --strict-gpg",
    )
    sp.set_defaults(run=cmd_ingest_blob)

    sp = sub.add_parser(
        "file-drop-poll",
        help="Poll registry inbound roots (or --root) and ingest sealed+ready pairs",
    )
    sp.add_argument("--queue", required=True)
    sp.add_argument("--privkey", required=True)
    sp.add_argument("--passphrase", default="")
    sp.add_argument("--registry", default="", help="YAML path; with --agent loads file_drop allowed_inbound_roots")
    sp.add_argument("--agent", default="", help="Peer agent_id for registry inbound roots")
    sp.add_argument("--root", action="append", default=[], help="Extra root dir (repeatable)")
    sp.add_argument("--extension", default=".agentq.asc")
    sp.add_argument("--lim", type=int, default=50)
    sp.add_argument(
        "--strict-gpg",
        action="store_true",
        help="Same as ingest-blob --strict-gpg for this poll run",
    )
    sp.add_argument(
        "--use-lockfile",
        action="store_true",
        help="fcntl lock on sealed before claim (shared NFS)",
    )
    sp.set_defaults(run=cmd_file_drop_poll)

    sp = sub.add_parser(
        "ship-file-drop-multi",
        help="Ship to each manifest.to_agent_ids using registry pubkeys",
    )
    sp.add_argument("--manifest", required=True, help="JSON manifest with to_agent_ids")
    sp.add_argument("--registry", required=True)
    sp.add_argument("--out", required=True)
    sp.add_argument("--stem", default="payload")
    sp.add_argument("--queue", default="")
    sp.add_argument("--skip-pre-ship", action="store_true")
    sp.add_argument("--signer-gnupghome", default="")
    sp.add_argument("--signer-uid", default="")
    sp.add_argument("--signer-passphrase", default="")
    sp.add_argument("--write-ready-sha256", action="store_true")
    sp.set_defaults(run=cmd_ship_file_drop_multi)

    sp = sub.add_parser(
        "ship-bundle",
        help="Tar.gz a directory into manifest attachment (max size cap); seal like ship-file-drop",
    )
    sp.add_argument("src_dir", help="Directory to pack")
    sp.add_argument("--pubkey", required=True, help="Recipient public key file")
    sp.add_argument("--out", required=True, help="Outbound directory")
    sp.add_argument("--stem", default="bundle", help="Stem for sealed files")
    sp.add_argument("--from-agent", default="local", dest="from_agent")
    sp.add_argument("--max-mb", type=int, default=20, help="Max tar.gz size in MB")
    sp.add_argument("--queue", default="", help="Queue root for ship_log")
    sp.add_argument("--signer-gnupghome", default="", help="Strict gpg signer homedir")
    sp.add_argument("--signer-uid", default="")
    sp.add_argument("--signer-passphrase", default="")
    sp.add_argument("--write-ready-sha256", action="store_true")
    sp.set_defaults(run=cmd_ship_bundle)

    sp = sub.add_parser("prune-processed", help="Remove processed/* dirs older than N days")
    sp.add_argument("processed_root", help="Path to processed directory")
    sp.add_argument("--days", type=float, default=30.0, help="Age threshold in days")
    sp.add_argument("--dry-run", action="store_true", help="List only, do not delete")
    sp.set_defaults(run=cmd_prune_processed)

    sp = sub.add_parser("doctor", help="gpg presence + optional registry-validate")
    sp.add_argument("--registry", default="", help="If set, run validate_registry with keys on disk")
    sp.set_defaults(run=cmd_doctor)

    sp = sub.add_parser("key-export", help="gpg --armor --export to file (needs GNUPGHOME + uid)")
    sp.add_argument("gnupghome", help="Signer keyring directory")
    sp.add_argument("uid", nargs="?", default="", help="User id to export (empty = all)")
    sp.add_argument("--output", "-o", required=True, help="Output .asc file")
    sp.set_defaults(run=cmd_key_export)

    sp = sub.add_parser("key-import", help="gpg --import pubkey into a GNUPGHOME")
    sp.add_argument("gnupghome", help="Target keyring directory (created if missing)")
    sp.add_argument("pubkey_file", help="Armored public key file")
    sp.set_defaults(run=cmd_key_import)

    args = p.parse_args()
    return args.run(args)
