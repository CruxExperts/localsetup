---
name: ls-cloudflare-dns
description: Manage Cloudflare DNS records with the flarectl CLI and guidance for safe zone surveys. Use when adding, changing, removing, listing, or auditing DNS records.
metadata:
  version: "1.1"
compatibility: "Guidance-only skill. Requires flarectl on PATH, outbound network access to Cloudflare, and a scoped Cloudflare API token. Future bundled helpers must use Python 3.10+ and approved requests/PyYAML dependencies when relevant."
---

# Cloudflare DNS management

## Purpose

Give an AI agent a safe workflow for managing DNS records in a Cloudflare account from the terminal. Covers list, create, modify, and delete operations across multiple zones, plus guidance for zone surveys.

This skill does not ship active Cloudflare tooling. It provides a safe operating workflow for using the external `flarectl` command directly. Add a reviewed Python helper in a future change before advertising wrapper commands such as `cf_dns.py`, `survey_dns_zones.py`, or `setup_survey_schedule.py`.

## When to use

- User asks to add, update, or remove a DNS record.
- User asks to list or inspect DNS records for a domain.
- User asks to plan or run a DNS zone survey or snapshot.
- Natural follow-on after creating an NPM proxy host (to create the matching A/CNAME record).

Do not use for Cloudflare Pages, Workers, or any Cloudflare service beyond DNS.

## Tooling (framework standard)

Current package mode is guidance-only plus external `flarectl` usage.

Requirements:
- Python 3.10+ only if a future helper script is added.
- Approved Python dependencies for future helpers: `requests` for Cloudflare HTTP API calls and PyYAML for YAML survey output.
- External binary: `flarectl` on PATH. See `references/flarectl-install.md`.
- Network access to Cloudflare API endpoints from the machine running `flarectl`.
- Cloudflare API token exposed through `flarectl`'s supported authentication environment.

## Inputs required

- Cloudflare API token with "Edit zone DNS" permission, provided through `flarectl`'s supported configuration or environment for your installation.
- For all operations: zone (domain name).
- For create: record name, type, content; optionally proxied flag.
- For modify/delete: record ID (fetched via list at operation time, never reused from memory).

## Directory layout

No `scripts/` directory is currently bundled with this skill. Keep local tokens and survey outputs outside the repo in a gitignored location.

## Workflow

### 1. Setup (first time)

1. Install flarectl (see `references/flarectl-install.md`).
2. Configure a scoped Cloudflare token according to `references/api-token-setup.md` and your `flarectl` installation.
3. Verify the installed command and flags: `flarectl dns --help`.
4. Verify access with a read-only list command for the target zone.

### 2. List records

```bash
flarectl dns --help
# Then use the installed version's list syntax for the target zone.
```

- Do not assume a default zone. Always ask the user which domain to list or infer from context.
- Present output as a table: name, type, content, proxied, ID.
- Record IDs are required for modify and delete; capture from this output.

### 3. Create record

Parameters to gather: `zone`, `name` (subdomain or `@` for apex), `type` (A/AAAA/CNAME/MX/TXT), `content`, and whether proxied.

```
flarectl dns create --zone=<domain> --name=<name> --type=<type> --content=<content> [--proxy]
```

After creation: confirm by showing output or re-listing the zone.

### 4. Modify record (destructive, double confirmation required)

Safety gates (mandatory):
1. User states intent.
2. Agent lists the record(s) that will change (zone, name, type, current content, proposed new content, record ID). Waits.
3. User must confirm with a phrase **containing the word "modify"** (e.g. "confirm modify"). Vague replies ("yes", "ok") are not accepted.

Steps:
1. List zone to get live record ID.
2. Show details and wait for second confirmation.
3. Apply update with the installed `flarectl dns update` syntax after verifying exact flags with `flarectl dns --help`.
4. Re-list to confirm.

Note: run `flarectl dns --help` to verify exact flags for the installed version.

### 5. Delete record (destructive, double confirmation required)

Safety gates (mandatory):
1. User states intent.
2. Agent shows exactly what will be deleted (zone, name, type, content, record ID). Waits.
3. User must confirm with a phrase **containing the word "delete"** (e.g. "confirm delete").

Steps:
1. List zone to get live record ID.
2. Show full record detail and wait for second confirmation.
3. Delete with the installed `flarectl dns delete` syntax after verifying exact flags with `flarectl dns --help`.
4. Confirm removal (re-list optional).

### 6. Zone survey

No survey script is bundled in this skill. For a survey, use `flarectl` read-only list commands per zone and store any report in a gitignored location. If automation is needed, create a tested Python 3.10+ helper using `requests` for Cloudflare API calls and PyYAML for optional YAML output before documenting or scheduling it.

Suggested report location: `~/.localsetup/context/dns/`.

Suggested report names, if a future helper or manual process writes them:
- `cloudflare_dns_survey.json`
- `cloudflare_dns_survey.yaml` when YAML output is intentionally produced

The agent may read the survey for read-only context (e.g. "what records point to this host"), but must always use a live `dns list` call for any modify or delete to get current record IDs.

### 7. Schedule survey

Use `ls-cron-orchestrator` only after a real survey command exists and has been tested. Do not schedule placeholder commands.

## Agent behavior rules

**Multi-zone (mandatory):**
- Never assume a single domain. Always ask for or infer the zone before running any command.
- Always pass `--zone=<domain>` explicitly.
- When the account has multiple zones, do not default to any one of them.

**Record IDs:**
- Always fetch the current record list before modify or delete. Do not guess or reuse IDs from a previous session.

**Error handling:**
- Surface non-zero flarectl exits to the user with the full error output.
- If the token is missing or authentication fails, direct the user to check the local `flarectl` configuration and the token's IP restrictions.

**Security:**
- Any token/config file must be gitignored and permissions set to `600`.
- Token should have only "Edit zone DNS" permission and an IP restriction for the machine's public IP.
- Survey output files contain record IDs and content; store in a gitignored location.

## Reference

- references/flarectl-install.md - flarectl install methods (Go, Homebrew, manual build)
- references/api-token-setup.md - Cloudflare API token creation guide
- references/survey-schema.md - Suggested zone survey report schema
