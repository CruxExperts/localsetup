---
name: ls-linux-patcher
description: Automated Linux server patching and Docker container updates. Use when the user asks to update, patch, or upgrade Linux servers, apply security updates, update Docker containers, check for system updates, or manage server maintenance across multiple hosts. Supports Ubuntu, Debian, RHEL, AlmaLinux, Rocky Linux, CentOS, Amazon Linux, and SUSE. Includes PatchMon integration for automatic host detection and intelligent Docker handling.
metadata:
  version: "1.1"
compatibility: "Python 3.10+ for patch_cli.py; plan-only Python helper. Use 'python scripts/patch_cli.py auto|host-only|host-full|multiple' to generate auditable commands; remote execution is manual."
---

# Linux Patcher

Automate Linux server patching and Docker container updates across multiple hosts via SSH.

## [WARNING] Important disclaimers

### Distribution support status

**Fully tested:**
- [OK] **Ubuntu** - Tested end-to-end with real infrastructure

**Supported but untested:**
- [WARNING] **Debian GNU/Linux** - Commands based on official documentation
- [WARNING] **Amazon Linux** - Supports both AL2 (yum) and AL2023 (dnf)
- [WARNING] **RHEL (Red Hat Enterprise Linux)** - Supports RHEL 7 (yum) and 8+ (dnf)
- [WARNING] **AlmaLinux** - RHEL-compatible, uses dnf
- [WARNING] **Rocky Linux** - RHEL-compatible, uses dnf
- [WARNING] **CentOS** - Supports CentOS 7 (yum) and 8+ (dnf)
- [WARNING] **SUSE/OpenSUSE** - Uses zypper package manager

**Testing Recommendation:**
Always test untested distributions in a non-production environment first. The script will warn you when running on untested distributions.

### Security Notice

This skill requires:
- **Passwordless sudo access** - Configured with restricted permissions
- **SSH key authentication** - No passwords stored or transmitted
- **PatchMon credentials** - Stored securely in user's home directory

**Read `references/setup.md` for complete security configuration guide.**

## Quick Start

### Automated (Recommended)

**Patch all hosts from PatchMon** (automatic detection):
```bash
python scripts/patch_cli.py auto
```

**Skip Docker updates** (packages only):
```bash
python scripts/patch_cli.py auto --skip-docker
```

**Preview changes** (dry-run):
```bash
python scripts/patch_cli.py auto --dry-run
```

### Manual (Alternative)

**Single host - packages only**:
```bash
python scripts/patch_cli.py host-only user@hostname
```

**Single host - full update**:
```bash
python scripts/patch_cli.py host-full user@hostname /path/to/docker/compose
```

**Multiple hosts from config**:
```bash
python scripts/patch_cli.py multiple config-file.conf
```

## Features

- **PatchMon integration** - Automatically detects hosts needing updates
- **Smart Docker detection** - Auto-detects Docker and Compose paths
- **Selective updates** - Skip Docker updates with `--skip-docker` flag
- **Passwordless sudo required** - Configure with `visudo` or `/etc/sudoers.d/` files
- **SSH key authentication** - No password prompts
- **Parallel execution** - Update multiple hosts simultaneously
- **Dry-run mode** - Preview changes without applying
- **Manual override** - Run updates on specific hosts without PatchMon

## Configuration

### Option 1: Automatic via PatchMon (Recommended)

Configure PatchMon credentials for automatic host detection:

Create a local, gitignored credentials file such as `~/.patchmon-credentials.conf` if you later add a tested PatchMon API client. The bundled helper is currently plan-only and does not read credentials.

Set your credentials:
```bash
PATCHMON_URL=https://patchmon.example.com
PATCHMON_USERNAME=your-username
PATCHMON_PASSWORD=your-password
```

Then simply run:
```bash
python scripts/patch_cli.py auto
```

The helper will emit a guidance-only plan for collecting PatchMon URL, credentials, target hosts, and a maintenance window. It does not query PatchMon or apply updates.

### Option 2: Single Host (Quick Manual)

Run scripts directly with command-line arguments (no config file needed).

### Option 3: Multiple Hosts (Manual Config)

Create a simple local config file with one host per line. Use `host` for package-only plans or `host,/absolute/docker/path` for full package-plus-Docker plans.

Example config:
```bash
ubuntu@webserver.example.com
root@database.example.com,/home/admin/compose
docker@monitor.example.com,/srv/monitoring
```

Then run:
```bash
python scripts/patch_cli.py multiple my-servers.conf
```

## Prerequisites

### Required on control machine (where you run the agent or scripts)

- [ ] **Shell or agent environment** (e.g. terminal, exec tool) to run the patch scripts
- [ ] **SSH client** installed (`ssh` command available)
- [ ] **Bash** 4.0 or higher
- [ ] **curl** installed (for PatchMon API)
- [ ] **jq** installed (for JSON parsing)
- [ ] **PatchMon** installed (required to check which hosts need updating)
  - Does NOT need to be on the same host as your agent
  - Can be installed on any server accessible via HTTPS
  - Download: https://github.com/PatchMon/PatchMon

**Install missing tools:**
```bash
# Ubuntu/Debian
sudo apt install curl jq

# RHEL/CentOS/Rocky/Alma
sudo dnf install curl jq

# macOS
brew install curl jq
```

### Required on Target Hosts

- [ ] **SSH server** running and accessible
- [ ] **SSH key authentication** configured (passwordless login)
- [ ] **Passwordless sudo** configured for patching commands (see references/setup.md)
- [ ] **Docker** installed (optional, only for full updates)
- [ ] **Docker Compose** installed (optional, only for full updates)
- [ ] **PatchMon agent** installed and reporting (optional but recommended)

### PatchMon Setup (Required for Automatic Mode)

**PatchMon is required to automatically detect which hosts need patching.**

**Important:** PatchMon does NOT need to be on the same server as your agent. Install PatchMon on a separate server; your agent (or you) query it via API.

**Download PatchMon:**
- **GitHub:** https://github.com/PatchMon/PatchMon
- **Documentation:** https://docs.patchmon.net

**What you need:**
- [ ] PatchMon server installed on ANY accessible server (not necessarily the agent/control host)
- [ ] PatchMon agents installed on all target hosts you want to patch
- [ ] PatchMon API credentials (username/password)
- [ ] Network connectivity from control/agent host to PatchMon server (HTTPS)

**Architecture:**
```
      HTTPS API
 Control / agent  >  PatchMon Server
 host                Query updates     (separate host)


                                                   Reports


                                          Target Hosts
                                          (with agents)

```

**Quick Start:**
1. Install PatchMon server on a separate server (see GitHub repo)
2. Install PatchMon agents on all hosts you want to patch
3. Configure the control machine to access PatchMon API:

```bash
install -m 600 /dev/null ~/.patchmon-credentials.conf
nano ~/.patchmon-credentials.conf  # Set PatchMon server URL if you later add a tested API client
```

**Detailed setup:**
See `references/patchmon-setup.md` for complete installation guide.

**Can I use this skill without PatchMon?**
Yes! You can use manual mode to target specific hosts without PatchMon. However, automatic detection of hosts needing updates requires PatchMon.

### On Target Hosts

**Required:**
- SSH server running
- Passwordless sudo for the SSH user (for `apt` and `docker` commands)
- PatchMon agent installed and reporting (for automatic mode)

**For full updates:**
- Docker and Docker Compose installed
- Docker Compose files exist at specified paths

### Configure Passwordless Sudo

On each target host, create `/etc/sudoers.d/patches`:

```bash
# For Ubuntu/Debian systems
username ALL=(ALL) NOPASSWD: /usr/bin/apt, /usr/bin/docker

# For RHEL/CentOS systems
username ALL=(ALL) NOPASSWD: /usr/bin/yum, /usr/bin/docker, /usr/bin/dnf
```

Replace `username` with your SSH user. Test with `sudo -l` to verify.

## Update Modes

### Host-Only Updates

Updates system packages only:
- Run `apt update && apt upgrade` (or `yum update` on RHEL)
- Remove unused packages (`apt autoremove`)
- **Does NOT** touch Docker containers

**When to use:**
- Hosts without Docker
- Security patches only
- Minimal downtime required

### Full Updates

Complete update cycle:
- Update system packages
- Clean Docker cache (`docker system prune`)
- Pull latest Docker images
- Recreate containers with new images
- **Causes brief service interruption**

**When to use:**
- Docker-based infrastructure
- Regular maintenance windows
- Application updates available

## Workflow

### Automatic Workflow (plan-only helper)

1. **Query PatchMon** - Fetch hosts needing updates via API
2. **For each host:**
   - SSH into host
   - Check if Docker is installed
   - Auto-detect Docker Compose path (if not specified)
   - Apply host-only OR full update based on Docker detection
3. **Report results** - Summary of successful/failed updates

### Host-Only Update Process

1. SSH into target host
2. Run `sudo apt update`
3. Run `sudo apt -y upgrade`
4. Run `sudo apt -y autoremove`
5. Report results

### Full Update Process

1. SSH into target host
2. Run `sudo apt update && upgrade && autoremove`
3. Navigate to Docker Compose directory
4. Run `sudo docker system prune -af` (cleanup)
5. Pull all Docker images listed in compose file
6. Run `sudo docker compose pull`
7. Run `sudo docker compose up -d` (recreate containers)
8. Report results

### Docker Detection Logic

When using automatic mode:
- **Docker installed + compose file found** -> Full update
- **Docker installed + no compose file** -> Host-only update
- **Docker not installed** -> Host-only update
- **--skip-docker flag set** -> Host-only update (ignores Docker)

## Docker Path Auto-Detection

When Docker path is not specified, the script checks these locations:

1. `/home/$USER/Docker/docker-compose.yml`
2. `/opt/docker/docker-compose.yml`
3. `/srv/docker/docker-compose.yml`
4. `$HOME/Docker/docker-compose.yml`
5. Current directory

**Override auto-detection:**
```bash
python scripts/patch_cli.py host-full user@host /custom/path
```

## Examples

### Example 1: Automatic update via PatchMon (recommended)
```bash
# First time: collect PatchMon details and maintenance window
python scripts/patch_cli.py auto
```

### Example 2: Automatic with dry-run
```bash
# Preview what would be updated
python scripts/patch_cli.py auto --dry-run

# Review output, then apply
python scripts/patch_cli.py auto
```

### Example 3: Skip Docker updates
```bash
# Update packages only, even if Docker is detected
python scripts/patch_cli.py auto --skip-docker
```

### Example 4: Manual single host, packages only
```bash
python scripts/patch_cli.py host-only admin@webserver.example.com
```

### Example 5: Manual single host, full update with custom Docker path
```bash
python scripts/patch_cli.py host-full docker@app.example.com /home/docker/production
```

### Example 6: Manual multiple hosts from config
```bash
python scripts/patch_cli.py multiple production-servers.conf
```

### Example 7: Via your agent or chat
If your platform supports natural language or chat, you can ask (e.g.):
- "Update my servers"
- "Patch all hosts that need updates"
- "Update packages only, skip Docker"

Run the scripts via your platform's command or terminal; use automatic mode (`python scripts/patch_cli.py auto`) to query PatchMon and report results.

## Troubleshooting

### PatchMon Integration Issues

#### "PatchMon credentials not found"
- The bundled helper is plan-only and does not read credentials. If you add a tested PatchMon API client later, create a local gitignored credentials file and document the exact path it reads.

#### "Failed to authenticate with PatchMon"
- Verify PatchMon URL is correct (without trailing slash)
- Check username and password
- Ensure PatchMon server is accessible: `curl -k https://patchmon.example.com/api/health`
- Check firewall rules

#### "No hosts need updates" but PatchMon shows updates available
- Verify PatchMon agents are running on target hosts: `systemctl status patchmon-agent`
- Check agent reporting intervals: `/etc/patchmon/config.yml`
- Force agent update: `patchmon-agent report`

### System Update Issues

#### "Permission denied" on apt/docker commands
- Configure passwordless sudo (see Prerequisites section)
- Test with: `ssh user@host sudo apt update`

#### "Connection refused"
- Verify SSH access: `ssh user@host echo OK`
- Check SSH keys are configured
- Verify hostname resolution

#### Docker Compose not found
- Specify full path: `python scripts/patch_cli.py host-full user@host /full/path`
- Or install Docker Compose on target host
- Auto-detection searches: `/home/user/Docker`, `/opt/docker`, `/srv/docker`

#### Containers fail to start after update
- Check logs: `ssh user@host "docker logs container-name"`
- Manually inspect: `ssh user@host "cd /docker/path && docker compose logs"`
- Rollback if needed: `ssh user@host "cd /docker/path && docker compose down && docker compose up -d"`

## Additional References

- `references/patchmon-security-and-distributions.md` - PatchMon integration, security notes, best practices, reboot handling, agent execution guidance, and distribution support details.
