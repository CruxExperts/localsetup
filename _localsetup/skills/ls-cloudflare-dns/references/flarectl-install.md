# flarectl install methods

## Option 1: Go install (recommended)

```bash
go install github.com/cloudflare/cloudflare-go/cmd/flarectl@latest
export PATH="$(go env GOPATH)/bin:$PATH"
```

## Option 2: Homebrew (Linux/macOS)

```bash
brew install flarectl
```

No local wrapper is bundled with this skill. Ensure `flarectl` is on PATH.

## Option 3: Manual build

```bash
git clone https://github.com/cloudflare/cloudflare-go
cd cloudflare-go
go build ./cmd/flarectl
install -m 0755 flarectl ~/.local/bin/flarectl
```

## Verify

```bash
flarectl --version
flarectl dns --help
```

## Authentication

`flarectl` supports Cloudflare API tokens through the `CF_API_TOKEN` environment variable. It also supports legacy API key authentication through `CF_API_KEY` and `CF_API_EMAIL`, but scoped API tokens are preferred for DNS work.

Reference: https://pkg.go.dev/github.com/cloudflare/cloudflare-go/cmd/flarectl
