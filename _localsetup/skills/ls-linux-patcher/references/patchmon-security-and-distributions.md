# PatchMon, Security, and Distributions

## PatchMon Integration (Optional)

For dashboard monitoring and scheduled patching, see `references/patchmon-setup.md`.

PatchMon provides:
- Web dashboard for update status
- Per-host package tracking
- Security update highlighting
- Update history

## Security Considerations

- **Passwordless sudo** is required for automation
  - Limit to specific commands (`apt`, `docker` only)
  - Use `/etc/sudoers.d/` files (easier to manage)
- **SSH keys** should be protected
  - Use passphrase-protected keys when possible
  - Restrict key permissions: `chmod 600 ~/.ssh/id_rsa`
- **Review updates** before applying in production
  - Use dry-run mode first
  - Test on staging environment
- **Schedule updates** during maintenance windows
  - Use your platform's scheduler or cron for automation
  - Coordinate with team for Docker updates (brief downtime)

## Best Practices

1. **Test first** - Run dry-run mode before applying changes
2. **Stagger updates** - Don't update all hosts simultaneously (avoid full outage)
3. **Monitor logs** - Check output for errors after updates
4. **Backup configs** - Keep Docker Compose files in version control
5. **Schedule wisely** - Update during low-traffic windows
6. **Document paths** - Maintain config files for infrastructure
7. **Reboot when needed** - Kernel updates require reboots (not automated)

## Reboot Management

The scripts do NOT automatically reboot hosts. After updates:

1. Check if reboot required: `ssh user@host "[ -f /var/run/reboot-required ] && echo YES || echo NO"`
2. Schedule manual reboots during maintenance windows
3. Use PatchMon dashboard to track reboot requirements

## Running patch scripts from an agent

Use your platform's command or terminal to run the patch scripts. Paths are relative to the skill directory (e.g. `_localsetup/skills/ls-linux-patcher/` or `_localsetup/skills/ls-linux-patcher/`); adjust for your layout.

- **Automatic mode:** Run `python scripts/patch_cli.py auto` (or `python scripts/patch_cli.py auto --skip-docker` for packages only). The script queries PatchMon for hosts needing updates, then runs package and optional Docker updates. Invoke via your platform's shell/exec/run capability.
- **Scheduling:** Use your platform's scheduler or system cron. Example (Linux cron): `0 2 * * * cd /path/to/ls-linux-patcher && python scripts/patch_cli.py auto`.
- **Manual mode:** For specific hosts, run `python scripts/patch_cli.py host-only user@host` or `python scripts/patch_cli.py host-full user@host /path/to/docker/compose` from your terminal or exec tool.
- **Secrets:** Store PatchMon credentials in your platform's secret store or in `~/.patchmon-credentials.conf`; see `references/patchmon-setup.md`.

**What automatic mode does:** Queries PatchMon for hosts needing updates, detects Docker on each host, updates system packages, and (unless `--skip-docker`) pulls Docker images and recreates containers. Docker updates are included by default; use `--skip-docker` to skip container updates.

## Documentation Files

This skill includes comprehensive documentation:

- **SKILL.md** (this file) - Overview and usage guide
- **references/setup.md** - Complete setup instructions with security best practices
- **references/workflows.md** - Visual workflow diagrams for all modes
- **references/patchmon-setup.md** - PatchMon installation and integration

**First time setup?** Read `references/setup.md` first - it provides step-by-step instructions for secure configuration.

**Want to understand the flow?** Check `references/workflows.md` for visual diagrams of how the skill operates.

## Supported Linux Distributions

| Distribution | Package Manager | Tested | Status |
|--------------|-----------------|--------|--------|
| Ubuntu | apt | [OK] Yes | Fully supported |
| Debian | apt | [WARNING] No | Supported (untested) |
| Amazon Linux 2 | yum | [WARNING] No | Supported (untested) |
| Amazon Linux 2023 | dnf | [WARNING] No | Supported (untested) |
| RHEL 7 | yum | [WARNING] No | Supported (untested) |
| RHEL 8+ | dnf | [WARNING] No | Supported (untested) |
| AlmaLinux | dnf | [WARNING] No | Supported (untested) |
| Rocky Linux | dnf | [WARNING] No | Supported (untested) |
| CentOS 7 | yum | [WARNING] No | Supported (untested) |
| CentOS 8+ | dnf | [WARNING] No | Supported (untested) |
| SUSE/OpenSUSE | zypper | [WARNING] No | Supported (untested) |

The skill automatically detects the distribution and selects the appropriate package manager.
