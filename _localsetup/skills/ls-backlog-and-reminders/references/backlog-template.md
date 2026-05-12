# Backlog template

Use this template when creating the canonical backlog file at `.localsetup/backlog.md`. Never store backlog or reminder state under `_localsetup/`; that directory is framework-owned source.

```markdown
# Backlog

*Last updated: YYYY-MM-DD*

## Overdue

- [ ] Short title (due: YYYY-MM-DD) optional note

## Due soon (next 7 days)

- [ ] Short title (due: YYYY-MM-DD) optional note

## No date (whenever)

- [ ] Short title - optional note

## Done

- [x] Short title (done: YYYY-MM-DD)
```

## Path precedence

1. Use `.localsetup/backlog.md` as the canonical Localsetup backlog.
2. Use root `BACKLOG.md` only when `.localsetup/backlog.md` does not exist or when the skill is running outside a Localsetup repo.
3. If both files exist, update `.localsetup/backlog.md` and tell the user that `BACKLOG.md` is legacy.

## Timezone rule

Resolve relative due dates with one consistent timezone: explicit user or environment timezone, then `LOCALSETUP_TIMEZONE`, then `TZ`, then host local timezone. Ask once before writing when the date would be ambiguous.
