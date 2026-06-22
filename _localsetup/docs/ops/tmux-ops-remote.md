---
status: ACTIVE
version: 4.2
owner_package: ls-workflow-ops-tmux-session
---

# Tmux ops tool: remote

**Purpose:** Use the managed `tmux_ops` workflow when the tmux server runs on a different host than the agent process.

For the local managed workflow, state layout, JSON examples, and agent script, see [tmux-ops-managed.md](tmux-ops-managed.md). This page only explains the remote wrapper behavior.

## Configuration

- `REMOTE_TMUX_HOST` - Hostname or IP of the machine where tmux runs. When set, `_localsetup/tools/tmux_ops` runs the Python tool over SSH on that host and returns the same JSON.
- `REMOTE_TMUX_CWD` - Optional repo path on the remote host. Default: `/opt/devzone/devops`.

## Flow

Use the same managed commands locally or remotely:

```bash
export REMOTE_TMUX_HOST=sh0t
./_localsetup/tools/tmux_ops pick
./_localsetup/tools/tmux_ops probe -t ops
./_localsetup/tools/tmux_ops run -t ops -- sudo apt update
```

The returned `attach_command`, `state_dir`, `log_path`, and `run_id` all refer to the remote host.
If `probe` or `run` returns `action_required: true`, attach on the remote tmux host with the returned `attach_command`, run `sudo -v` in that exact pane, enter the password, then tell the agent `sudo ready` so it can probe again.

If a run returns `status: "running"`, keep watching by run ID:

```bash
./_localsetup/tools/tmux_ops status -t ops --run-id <run_id> --wait --timeout 120
```

Interrupt only through the managed cancel path:

```bash
./_localsetup/tools/tmux_ops cancel -t ops --run-id <run_id>
```

## Agent rules

- Do not use raw SSH plus tmux commands.
- Do not assume local `/tmp/localsetup-tmux-ops` contains remote status.
- Do not start another `run` while the remote session has an active `run_id`.
- If sudo returns `password_required`, ask the user to attach to the remote tmux session and enter the password there.

## When not to set it

If the agent process already runs on the same host as tmux, do not set `REMOTE_TMUX_HOST`. Run `_localsetup/tools/tmux_ops` directly.
