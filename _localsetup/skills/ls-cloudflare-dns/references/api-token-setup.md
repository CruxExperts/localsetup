# Cloudflare API token setup

1. Log in to https://dash.cloudflare.com/.
2. Go to **My Profile > API Tokens > Create Token**.
3. Use Cloudflare's DNS edit template, or create a custom token with:
   - Permissions: Zone > DNS > Write/Edit, plus read/list access needed by the installed `flarectl` command.
   - Zone resources: Include > All zones (or specific zones)
   - IP restrictions (recommended): add the public IP(s) of the machine(s) calling the API.
4. Export the token in the environment used to run `flarectl`:

```bash
export CF_API_TOKEN=your_token_here
```

If you persist the token in a shell profile, systemd environment file, or other local config file, keep that file outside the repo, ensure it is gitignored, and set permissions to `600`.

**Multi-machine note:** Each machine needs its public IP whitelisted, or use separate tokens per machine. Do not use a token with no IP restriction across multiple machines.

References:
- Cloudflare token creation: https://developers.cloudflare.com/fundamentals/api/get-started/create-token/
- Cloudflare token permissions: https://developers.cloudflare.com/fundamentals/api/reference/permissions/
- flarectl authentication environment: https://pkg.go.dev/github.com/cloudflare/cloudflare-go/cmd/flarectl
