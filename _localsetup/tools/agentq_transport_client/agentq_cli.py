#!/usr/bin/env python3
# Purpose: Thin CLI for Agent Q transport client (version, PRD stamp, key doctor stubs).
# Created: 2026-03-09
# Last updated: 2026-03-09

"""Run from repo root: python3 _localsetup/tools/agentq_transport_client/agentq_cli.py <cmd>"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_ENGINE = _ROOT.parent.parent
sys.path.insert(0, str(_ENGINE))
sys.path.insert(0, str(_ROOT))


def cmd_version(_args: argparse.Namespace) -> int:
    from agentq_transport_client.version_util import read_framework_hash, read_framework_version

    print("localsetup_framework_version:", read_framework_version())
    h = read_framework_hash()
    if h:
        print("localsetup_framework_hash:", h)
    return 0


def cmd_stamp_prd(args: argparse.Namespace) -> int:
    from agentq_transport_client.prd_stamp import ensure_prd_stamp

    path = Path(args.path)
    # PRD stamping is for queue specs; warn if path looks like a framework doc
    parts = {p.lower() for p in path.parts}
    if "_localsetup/docs" in str(path) and path.suffix.lower() == ".md" and "queue" not in str(path) and ".agent" not in str(path):
        sys.stderr.write(
            "[WARN] stamp-prd is for PRD/queue specs under .agent/queue or prds/; use only on handoff specs.\n"
        )
    modified = ensure_prd_stamp(path, add_hash=args.hash)
    if modified:
        print("Stamped:", path)
    else:
        print("No change (already stamped or hash skipped):", path)
    return 0


def cmd_key_fingerprint(args: argparse.Namespace) -> int:
    """Print OpenPGP key fingerprint from armored file when PGPy is available."""
    path = Path(args.path)
    if not path.is_file():
        sys.stderr.write("[FAIL] Not a file: %s\n" % path)
        return 1
    try:
        import pgpy  # type: ignore
    except ImportError:
        sys.stderr.write("[FAIL] PGPy required: pip install PGPy\n")
        return 2
    key, _ = pgpy.PGPKey.from_file(str(path))
    fp = key.fingerprint.replace(" ", "")
    print("fingerprint:", fp)
    return 0


def cmd_key_gen(args: argparse.Namespace) -> int:
    from agentq_transport_client.keygen import generate_keypair_gnupg

    out = Path(args.output)
    try:
        pub, priv, fp = generate_keypair_gnupg(out)
    except Exception as exc:
        sys.stderr.write("[FAIL] %s\n" % exc)
        return 1
    print("public:", pub)
    print("secret:", priv)
    print("fingerprint:", fp)
    return 0


def cmd_registry_validate(args: argparse.Namespace) -> int:
    from agentq_transport_client.registry import load_registry_yaml, validate_registry

    try:
        raw = load_registry_yaml(Path(args.path))
        v = validate_registry(raw, require_keys_exist=not args.skip_keys)
    except Exception as exc:
        sys.stderr.write("[FAIL] %s\n" % exc)
        return 1
    print("[OK] registry valid; agents:", list(v["raw"]["agents"].keys()))
    print("fingerprints:", len(v["fp_to_agent"]))
    return 0


def cmd_mail_pull(args: argparse.Namespace) -> int:
    from agentq_transport_client.mail_adapter import mail_pull_and_promote

    policy = Path(args.policy)
    accounts = Path(args.accounts)
    r = mail_pull_and_promote(
        queue_root=Path(args.queue),
        account_id=args.account,
        policy_path=policy,
        accounts_path=accounts,
        mailbox=args.mailbox,
        post_ingest_mailbox=args.post_mailbox,
        query=args.query,
        lim=args.lim,
        confirm_token=args.confirm_token or "",
        registry_path=Path(args.registry) if getattr(args, "registry", None) else None,
    )
    import json

    print(json.dumps(r, indent=2))
    return 0 if all(x.get("status") not in ("error",) for x in r if isinstance(x, dict)) else 1


def cmd_ship_file_drop(args: argparse.Namespace) -> int:
    from agentq_transport_client.ship import load_manifest_from_path, ship_file_drop

    if args.manifest:
        manifest = load_manifest_from_path(Path(args.manifest))
    else:
        import json

        if not (args.manifest_json or "").strip() or args.manifest_json.strip() == "{}":
            sys.stderr.write("[FAIL] Provide --manifest or non-empty --manifest-json\n")
            return 1
        manifest = json.loads(args.manifest_json)
    r = ship_file_drop(
        manifest,
        Path(args.pubkey),
        Path(args.out),
        stem=args.stem,
        queue_root=Path(args.queue) if getattr(args, "queue", None) else None,
        skip_pre_ship=args.skip_pre_ship,
        pre_ship_cwd=Path(args.pre_ship_cwd) if getattr(args, "pre_ship_cwd", None) else None,
        signer_gnupghome=Path(args.signer_gnupghome) if getattr(args, "signer_gnupghome", None) else None,
        signer_uid=getattr(args, "signer_uid", "") or "",
        signer_passphrase=getattr(args, "signer_passphrase", "") or "",
        write_ready_sha256=getattr(args, "write_ready_sha256", False),
    )
    print(r)
    return 0 if r.get("status") == "ok" else 1


def cmd_mail_move_retry(args: argparse.Namespace) -> int:
    from agentq_transport_client.mail_adapter import mail_retry_pending_moves

    r = mail_retry_pending_moves(
        queue_root=Path(args.queue),
        account_id=args.account,
        policy_path=Path(args.policy),
        accounts_path=Path(args.accounts),
        confirm_token=args.confirm_token or "",
    )
    import json

    print(json.dumps(r, indent=2))
    return 0 if all(x.get("ok") for x in r) else 1


def cmd_archive_prune(args: argparse.Namespace) -> int:
    from agentq_transport_client.queue_archive import prune_archive

    r = prune_archive(
        Path(args.archive_root),
        older_than_days=args.days if args.days > 0 else None,
        max_total_gb=args.max_gb if args.max_gb > 0 else None,
        dry_run=args.dry_run,
    )
    print(r)
    return 0


def cmd_queue_pending(args: argparse.Namespace) -> int:
    from agentq_transport_client.queue_ops import (
        list_in_ready,
        move_ack_required_to_pending,
        move_to_pending,
    )

    if getattr(args, "list_only", False):
        import json

        print(json.dumps(list_in_ready(Path(args.queue)), indent=2))
        return 0
    if args.transport_id:
        r = move_to_pending(Path(args.queue), args.transport_id)
        print(r)
        return 0 if r.get("status") == "ok" else 1
    r = move_ack_required_to_pending(Path(args.queue))
    print(r)
    return 0


def cmd_ship_mail(args: argparse.Namespace) -> int:
    from agentq_transport_client.mail_adapter import mail_ship_agentq_outer
    from agentq_transport_client.ship import load_manifest_from_path

    if args.manifest:
        manifest = load_manifest_from_path(Path(args.manifest))
    else:
        import json

        if not (args.manifest_json or "").strip() or args.manifest_json.strip() == "{}":
            sys.stderr.write("[FAIL] Provide --manifest or non-empty --manifest-json\n")
            return 1
        manifest = json.loads(args.manifest_json)
    r = mail_ship_agentq_outer(
        account_id=args.account,
        policy_path=Path(args.policy),
        accounts_path=Path(args.accounts),
        manifest=manifest,
        to_addr=args.to,
        subject=args.subject,
        from_addr=args.from_addr,
        queue_root=Path(args.queue) if getattr(args, "queue", None) else None,
        skip_pre_ship=args.skip_pre_ship,
        pre_ship_cwd=Path(args.pre_ship_cwd) if getattr(args, "pre_ship_cwd", None) else None,
    )
    import json

    print(json.dumps(r, indent=2))
    return 0 if r.get("ok") else 1


def cmd_ship_mail_strict(args: argparse.Namespace) -> int:
    from agentq_transport_client.mail_adapter import mail_ship_strict_gpg
    from agentq_transport_client.ship import load_manifest_from_path

    if args.manifest:
        manifest = load_manifest_from_path(Path(args.manifest))
    else:
        import json

        manifest = json.loads(args.manifest_json or "{}")
    pub = Path(args.pubkey).read_text(encoding="utf-8", errors="replace")
    r = mail_ship_strict_gpg(
        account_id=args.account,
        policy_path=Path(args.policy),
        accounts_path=Path(args.accounts),
        manifest=manifest,
        to_addr=args.to,
        subject=args.subject,
        from_addr=args.from_addr,
        recipient_pubkey_armored=pub,
        signer_gnupghome=Path(args.signer_gnupghome),
        signer_uid=args.signer_uid or "",
        signer_passphrase=args.signer_passphrase or "",
        queue_root=Path(args.queue) if args.queue else None,
        skip_pre_ship=args.skip_pre_ship,
        pre_ship_cwd=Path(args.pre_ship_cwd) if args.pre_ship_cwd else None,
    )
    import json

    print(json.dumps(r, indent=2))
    return 0 if r.get("ok") else 1


def cmd_ingest_blob(args: argparse.Namespace) -> int:
    from agentq_transport_client import ingest as ingest_mod
    from agentq_transport_client.ingest import ingest_file_drop_blob

    if getattr(args, "strict_gpg", False):
        ingest_mod.ingest_file_drop_blob._strict_gpg = True  # type: ignore[attr-defined]
    priv = Path(args.privkey).read_text(encoding="utf-8", errors="replace")
    r = ingest_file_drop_blob(
        Path(args.blob),
        queue_root=Path(args.queue),
        recipient_private_armored=priv,
        passphrase=args.passphrase or "",
        sealed_extension=args.extension,
        force=args.force,
        operator=args.operator or "",
        reason=args.reason or "",
        registry_path=Path(args.registry) if getattr(args, "registry", None) else None,
        recipient_gnupghome=Path(args.recipient_gnupghome)
        if getattr(args, "recipient_gnupghome", None)
        else None,
    )
    print(r)
    return 0 if r.get("status") in ("ok", "skipped") else 1


def cmd_file_drop_poll(args: argparse.Namespace) -> int:
    from agentq_transport_client.ingest import run_file_drop_poll
    from agentq_transport_client.registry import (
        file_drop_inbound_roots,
        load_registry_yaml,
        validate_registry,
    )

    priv = Path(args.privkey).read_text(encoding="utf-8", errors="replace")
    roots: list[Path] = []
    if args.registry and args.agent:
        raw = load_registry_yaml(Path(args.registry))
        validated = validate_registry(raw, require_keys_exist=False)
        roots = file_drop_inbound_roots(validated, args.agent)
    if args.root:
        roots.extend(Path(p) for p in args.root)
    if not roots:
        sys.stderr.write("[FAIL] No roots: use --registry + --agent or --root\n")
        return 1
    r = run_file_drop_poll(
        roots,
        queue_root=Path(args.queue),
        recipient_private_armored=priv,
        passphrase=args.passphrase or "",
        sealed_extension=args.extension,
        max_per_poll=args.lim,
        registry_path=Path(args.registry) if args.registry else None,
        strict_gpg=getattr(args, "strict_gpg", False),
        use_lockfile=getattr(args, "use_lockfile", False),
    )
    import json

    print(json.dumps(r, indent=2))
    return 0


def cmd_ship_file_drop_multi(args: argparse.Namespace) -> int:
    from agentq_transport_client.ship import load_manifest_from_path, ship_file_drop_multi

    manifest = load_manifest_from_path(Path(args.manifest))
    kw = {}
    if args.queue:
        kw["queue_root"] = Path(args.queue)
    if args.skip_pre_ship:
        kw["skip_pre_ship"] = True
    if args.signer_gnupghome:
        kw["signer_gnupghome"] = Path(args.signer_gnupghome)
        kw["signer_uid"] = args.signer_uid or ""
        kw["signer_passphrase"] = args.signer_passphrase or ""
    if args.write_ready_sha256:
        kw["write_ready_sha256"] = True
    r = ship_file_drop_multi(
        manifest, Path(args.registry), Path(args.out), stem=args.stem, **kw
    )
    print(r)
    return 0 if all(x.get("status") == "ok" for x in r if isinstance(x, dict)) else 1


def cmd_ship_bundle(args: argparse.Namespace) -> int:
    from agentq_transport_client.bundle import ship_bundle_file_drop

    r = ship_bundle_file_drop(
        Path(args.src_dir),
        Path(args.pubkey),
        Path(args.out),
        args.stem,
        from_agent_id=args.from_agent,
        max_bytes=int(args.max_mb) * 1024 * 1024,
        queue_root=Path(args.queue) if args.queue else None,
        signer_gnupghome=Path(args.signer_gnupghome) if args.signer_gnupghome else None,
        signer_uid=args.signer_uid or "",
        signer_passphrase=args.signer_passphrase or "",
        write_ready_sha256=getattr(args, "write_ready_sha256", False),
    )
    print(r)
    return 0 if r.get("status") == "ok" else 1


def cmd_prune_processed(args: argparse.Namespace) -> int:
    from agentq_transport_client.prune import prune_processed

    r = prune_processed(
        Path(args.processed_root),
        older_than_days=args.days,
        dry_run=args.dry_run,
    )
    print(r)
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    import shutil
    import subprocess

    gpg = shutil.which("gpg") or shutil.which("gpg2")
    if gpg:
        r = subprocess.run([gpg, "--version"], capture_output=True, text=True, timeout=5)
        print(r.stdout.splitlines()[0] if r.stdout else "gpg ok")
    else:
        print("gpg not on PATH (required for key-gen and strict sign-then-encrypt).")
    if getattr(args, "registry", None):
        from agentq_transport_client.registry import load_registry_yaml, validate_registry

        try:
            raw = load_registry_yaml(Path(args.registry))
            validate_registry(raw, require_keys_exist=True)
            print("registry-validate: ok")
        except Exception as e:
            print(f"registry-validate: FAIL {e}")
            return 1
    return 0


def cmd_key_export(args: argparse.Namespace) -> int:
    import subprocess

    gh = Path(args.gnupghome)
    if not gh.is_dir():
        sys.stderr.write(f"[FAIL] GNUPGHOME not a directory: {gh}\n")
        return 1
    out = Path(args.output)
    r = subprocess.run(
        ["gpg", "--homedir", str(gh), "--batch", "-a", "--export", args.uid or ""],
        capture_output=True,
        timeout=30,
    )
    if r.returncode != 0:
        sys.stderr.write(r.stderr.decode(errors="replace")[:500])
        return 1
    out.write_bytes(r.stdout)
    print(f"exported -> {out}")
    return 0


def cmd_key_import(args: argparse.Namespace) -> int:
    import subprocess

    gh = Path(args.gnupghome)
    gh.mkdir(parents=True, exist_ok=True)
    pub = Path(args.pubkey_file)
    r = subprocess.run(
        ["gpg", "--homedir", str(gh), "--batch", "--import", str(pub)],
        capture_output=True,
        timeout=30,
    )
    sys.stdout.write(r.stderr.decode(errors="replace"))
    return 0 if r.returncode == 0 else 1


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
    sp.add_argument("--policy", default="_localsetup/config/mail_protocol_policy.yaml")
    sp.add_argument("--accounts", default="_localsetup/config/mail_accounts.json")
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
    sp.add_argument("--policy", default="_localsetup/config/mail_protocol_policy.yaml")
    sp.add_argument("--accounts", default="_localsetup/config/mail_accounts.json")
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
    sp.add_argument("--policy", default="_localsetup/config/mail_protocol_policy.yaml")
    sp.add_argument("--accounts", default="_localsetup/config/mail_accounts.json")
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
    sp.add_argument("--policy", default="_localsetup/config/mail_protocol_policy.yaml")
    sp.add_argument("--accounts", default="_localsetup/config/mail_accounts.json")
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


if __name__ == "__main__":
    sys.exit(main())
