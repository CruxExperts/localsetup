from __future__ import annotations

import argparse
import sys
from pathlib import Path

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
    if "ls/docs" in str(path) and path.suffix.lower() == ".md" and "queue" not in str(path) and ".agent" not in str(path):
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
    from lib.deps import require_deps

    path = Path(args.path)
    if not path.is_file():
        sys.stderr.write("[FAIL] Not a file: %s\n" % path)
        return 1
    require_deps(["pgpy"])
    import pgpy  # type: ignore

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
    return 0 if all(x.get("status") == "ok" for x in r) else 1


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
