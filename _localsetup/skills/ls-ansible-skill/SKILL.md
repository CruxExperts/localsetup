---
name: ls-ansible-skill
description: "Infrastructure automation with Ansible. Use for server provisioning, configuration management, application deployment, and multi-host orchestration. Includes example playbooks for VPS setup, security hardening, and common server configurations. Bundled examples may reference one platform; adapt paths and commands for your environment."
metadata:
  version: "1.1"
compatibility: "Requires Ansible 8+ or ansible-core 2.15+, ansible-playbook, ansible-galaxy, and collections community.general 8+ plus ansible.posix 1.5+."
---

# Ansible Skill

Infrastructure as Code automation for server provisioning, configuration management, and orchestration.

## Quick Start

## Compatibility

The bundled example targets Ansible 8+ or ansible-core 2.15+ and requires these collections:

- `community.general` 8.0.0 or newer
- `ansible.posix` 1.5.0 or newer

### Prerequisites

```bash
# Install Ansible
uv tool install ansible

# Or on macOS
brew install ansible

# Verify
ansible --version
```

From `assets/ansible-example`, install the required collections:

```bash
cd assets/ansible-example
ansible-galaxy collection install -r collections/requirements.yml
```

### Run Your First Playbook

```bash
# Test connection
ansible all -i inventory/hosts.yml -m ping

# Run playbook
ansible-playbook -i inventory/hosts.yml playbooks/site.yml

# Dry run (check mode)
ansible-playbook -i inventory/hosts.yml playbooks/site.yml --check

# With specific tags
ansible-playbook -i inventory/hosts.yml playbooks/site.yml --tags "security,nodejs"
```

## Directory Structure

```
assets/ansible-example/
  ansible.cfg
  collections/
    requirements.yml  # community.general and ansible.posix
  inventory/
    hosts.yml
    group_vars/
      all.yml
  playbooks/
    site.yml
    agent-host-vps.yml
    security.yml
    update.yml
  roles/
    common/
    security/
      templates/
        jail.local.j2
    nodejs/
    agent-host/
      templates/
        agent-host.service.j2
references/
  best-practices.md
  modules-cheatsheet.md
  troubleshooting.md
```

## Core Concepts

### Inventory

Define your hosts in `inventory/hosts.yml`:

```yaml
all:
  children:
    vps:
      hosts:
        example_vps:
          ansible_host: 203.0.113.10
          ansible_user: deploy
          ansible_ssh_private_key_file: "~/.ssh/id_ed25519_example"

    agent_hosts:
      hosts:
        example_agent_host:
```

### Playbooks

Entry points for automation:

```yaml
# playbooks/site.yml - Master playbook
---
- name: Configure all servers
  hosts: all
  become: yes
  roles:
    - common
    - security

- name: Agent host servers
  hosts: agent_hosts
  become: yes
  roles:
    - nodejs
    - agent-host
```

### Roles

Reusable, modular configurations:

```yaml
# roles/common/tasks/main.yml
---
- name: Update apt cache
  ansible.builtin.apt:
    update_cache: yes
    cache_valid_time: 3600
  when: ansible_os_family == "Debian"

- name: Install essential packages
  ansible.builtin.apt:
    name:
      - curl
      - wget
      - git
      - htop
      - vim
      - unzip
    state: present
```

## Included Roles

### 1. common
Base system configuration:
- System updates
- Essential packages
- Timezone configuration
- User creation with SSH keys

### 2. security
Hardening following CIS benchmarks:
- SSH hardening (key-only, no root)
- fail2ban for brute-force protection
- UFW firewall configuration
- Automatic security updates

### 3. nodejs
Node.js installation via NodeSource:
- Configurable version (default: 22.x LTS)
- npm global packages
- pm2 process manager (optional)

### 4. agent-host
Generic agent-host role. The bundled defaults install OpenClaw as a sample npm-based agent service, but the role name, playbook, group, and variables are intentionally generic so you can change the package, command, config path, and service name without renaming files.

## Usage Patterns

### Pattern 1: New VPS setup (example: agent host)

Bundled playbook `agent-host-vps.yml` is the verified VPS/agent-host example.

```bash
# 1. Add host to inventory
cat >> inventory/hosts.yml << 'EOF'
        new_server:
          ansible_host: 203.0.113.20
          ansible_user: deploy
          ansible_ssh_private_key_file: "~/.ssh/id_ed25519_example"
          deploy_user: deploy
          deploy_ssh_pubkey: "ssh-ed25519 AAAA... user@example"
EOF

# 2. Run VPS/agent-host playbook
ansible-playbook -i inventory/hosts.yml playbooks/agent-host-vps.yml \
  --limit new_server \
  --ask-vault-pass

# 3. After initial setup, update inventory to use key auth
# ansible_user: deploy
# ansible_ssh_private_key_file: ~/.ssh/id_ed25519_example
```

### Pattern 2: Security Hardening Only

```bash
ansible-playbook -i inventory/hosts.yml playbooks/security.yml \
  --limit production \
  --tags "ssh,firewall"
```

### Pattern 3: Rolling Updates

```bash
# Update one server at a time
ansible-playbook -i inventory/hosts.yml playbooks/update.yml \
  --serial 1
```

### Pattern 4: Ad-hoc Commands

```bash
# Check disk space on all servers
ansible all -i inventory/hosts.yml -m shell -a "df -h"

# Restart the sample agent-host service
ansible agent_hosts -i inventory/hosts.yml -m systemd -a "name=openclaw state=restarted"

# Copy file
ansible all -i inventory/hosts.yml -m copy -a "src=./file.txt dest=/tmp/"
```

## Variables & Secrets

### Group Variables

```yaml
# inventory/group_vars/all.yml
---
timezone: Etc/UTC
deploy_user: deploy
ssh_port: 22

# Security
security_ssh_password_auth: false
security_ssh_permit_root: false
security_fail2ban_enabled: true
security_ufw_enabled: true
security_ufw_allowed_ports:
  - 22
  - 80
  - 443

# Node.js
nodejs_version: "22.x"

# Agent-host sample defaults
agent_host_package_name: openclaw
agent_host_command: openclaw
agent_host_service_name: openclaw
```

### Vault for Secrets

```bash
# Create encrypted vars file
ansible-vault create inventory/group_vars/all/vault.yml

# Edit encrypted file
ansible-vault edit inventory/group_vars/all/vault.yml

# Run with vault
ansible-playbook site.yml --ask-vault-pass

# Or use vault password file
ansible-playbook site.yml --vault-password-file ~/.vault_pass
```

Vault file structure:
```yaml
# inventory/group_vars/all/vault.yml
---
vault_example_password: "replace-with-vaulted-value"
vault_api_token: "replace-with-vaulted-value"
```

## Common Modules

| Module | Purpose | Example |
|--------|---------|---------|
| `apt` | Package management (Debian) | `apt: name=nginx state=present` |
| `yum` | Package management (RHEL) | `yum: name=nginx state=present` |
| `copy` | Copy files | `copy: src=file dest=/path/` |
| `template` | Template files (Jinja2) | `template: src=nginx.conf.j2 dest=/etc/nginx/nginx.conf` |
| `file` | File/directory management | `file: path=/dir state=directory mode=0755` |
| `user` | User management | `user: name=deploy groups=sudo shell=/bin/bash` |
| `authorized_key` | SSH keys | `authorized_key: user=deploy key="{{ ssh_key }}"` |
| `systemd` | Service management | `systemd: name=nginx state=started enabled=yes` |
| `ufw` | Firewall (Ubuntu) | `ufw: rule=allow port=22 proto=tcp` |
| `lineinfile` | Edit single line | `lineinfile: path=/etc/ssh/sshd_config regexp='^PermitRootLogin' line='PermitRootLogin no'` |
| `git` | Clone repos | `git: repo=https://github.com/x/y.git dest=/opt/y` |
| `npm` | npm packages | `npm: name=openclaw global=yes` |
| `command` | Run command | `command: /opt/script.sh` |
| `shell` | Run shell command | `shell: cat /etc/passwd \| grep root` |

## Best Practices

### 1. Always Name Tasks
```yaml
# Good
- name: Install nginx web server
  apt:
    name: nginx
    state: present

# Bad
- apt: name=nginx
```

### 2. Use FQCN (Fully Qualified Collection Names)
```yaml
# Good
- ansible.builtin.apt:
    name: nginx

# Acceptable but less clear
- apt:
    name: nginx
```

### 3. Explicit State
```yaml
# Good - explicit state
- ansible.builtin.apt:
    name: nginx
    state: present

# Bad - implicit state
- ansible.builtin.apt:
    name: nginx
```

### 4. Idempotency
Write tasks that can run multiple times safely:
```yaml
# Good - idempotent
- name: Ensure config line exists
  ansible.builtin.lineinfile:
    path: /etc/ssh/sshd_config
    regexp: '^PasswordAuthentication'
    line: 'PasswordAuthentication no'

# Bad - not idempotent
- name: Add config line
  ansible.builtin.shell: echo "PasswordAuthentication no" >> /etc/ssh/sshd_config
```

### 5. Use Handlers for Restarts
```yaml
# tasks/main.yml
- name: Update SSH config
  ansible.builtin.template:
    src: sshd_config.j2
    dest: /etc/ssh/sshd_config
  notify: Restart SSH

# handlers/main.yml
- name: Restart SSH
  ansible.builtin.systemd:
    name: sshd
    state: restarted
```

### 6. Tags for Selective Runs
```yaml
- name: Security tasks
  ansible.builtin.include_tasks: security.yml
  tags: [security, hardening]

- name: App deployment
  ansible.builtin.include_tasks: deploy.yml
  tags: [deploy, app]
```

## Troubleshooting

### Connection Issues

```bash
# Test SSH connection manually
ssh -v user@host

# Debug Ansible connection
ansible host -i inventory -m ping -vvv

# Check inventory parsing
ansible-inventory -i inventory --list
```

### Common Errors

**"Permission denied"**
- Check SSH key permissions: `chmod 600 ~/.ssh/id_*`
- Verify user has sudo access
- Add `become: yes` to playbook

**"Host key verification failed"**
- Add to ansible.cfg: `host_key_checking = False`
- Or add host key: `ssh-keyscan -H host >> ~/.ssh/known_hosts`

**"Module not found"**
- Use FQCN: `ansible.builtin.apt` instead of `apt`
- Install collections: `ansible-galaxy collection install -r collections/requirements.yml`

### Debugging Playbooks

```bash
# Verbose output
ansible-playbook site.yml -v    # Basic
ansible-playbook site.yml -vv   # More
ansible-playbook site.yml -vvv  # Maximum

# Step through tasks
ansible-playbook site.yml --step

# Start at specific task
ansible-playbook site.yml --start-at-task="Install nginx"

# Check mode (dry run)
ansible-playbook site.yml --check --diff
```

## Running playbooks from an agent

Use your platform's command or terminal tool to run ansible-playbook (or the skill's main commands). Paths in examples are relative to the skill directory or repo root; adjust for your layout.

- **Running playbooks:** Invoke the playbook via your platform's shell/exec/run capability (e.g. terminal, exec tool, or run command). Example: `ansible-playbook -i inventory/hosts.yml playbooks/site.yml --limit <host>`.
- **Secrets:** Store credentials in your platform's secret store or use Ansible Vault; pass vault password via `--ask-vault-pass` or a vault password file. Do not hardcode secrets in the skill or inventory.

Some platforms offer secret managers; use them if available, otherwise Ansible Vault is the standard approach.

## References

- `references/best-practices.md` - Detailed best practices guide
- `references/modules-cheatsheet.md` - Common modules quick reference
- `references/troubleshooting.md` - Extended troubleshooting guide

## External Resources

- [Ansible Documentation](https://docs.ansible.com/)
- [Ansible Galaxy](https://galaxy.ansible.com/) - Community roles
- [geerlingguy roles](https://github.com/geerlingguy?tab=repositories&q=ansible-role) - High quality roles
- [Ansible for DevOps](https://www.ansiblefordevops.com/) - Book by Jeff Geerling
