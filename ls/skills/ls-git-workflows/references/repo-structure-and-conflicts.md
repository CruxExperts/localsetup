# Repository Structure and Conflicts

Use these recipes when managing shared code layouts, sparse monorepo checkouts,
or merge and rebase conflicts.

## Subtree and Submodule

### Subtree

Subtree copies code into your repository and does not require special clone
commands for collaborators.

```bash
# Add a subtree.
git subtree add --prefix=lib/shared https://github.com/org/shared-lib.git main --squash

# Pull updates from upstream.
git subtree pull --prefix=lib/shared https://github.com/org/shared-lib.git main --squash

# Push local changes back to upstream.
git subtree push --prefix=lib/shared https://github.com/org/shared-lib.git main

# Split subtree into its own branch for extraction.
git subtree split --prefix=lib/shared -b shared-lib-standalone
```

### Submodule

Submodule records a pointer to another repository at a specific commit.

```bash
# Add a submodule.
git submodule add https://github.com/org/shared-lib.git lib/shared

# Clone a repo with submodules.
git clone --recurse-submodules https://github.com/org/main-repo.git

# Initialize submodules after cloning without --recurse-submodules.
git submodule update --init --recursive

# Update submodules to latest.
git submodule update --remote

# Remove a submodule.
git rm lib/shared
rm -rf .git/modules/lib/shared
# Remove the entry from .gitmodules if it persists.
```

### Which One to Use

```text
Subtree: Simpler, no special commands for cloners, code lives in your repo.
Use when: shared library, vendor code, infrequent upstream changes.

Submodule: Pointer to exact commit, smaller repo, clear separation.
Use when: large dependency, independent release cycle, many contributors.
```

## Sparse Checkout

### Check Out Only Needed Directories

```bash
# Enable sparse checkout.
git sparse-checkout init --cone

# Select directories.
git sparse-checkout set packages/my-app packages/shared-lib

# Add another directory.
git sparse-checkout add packages/another-lib

# List what is checked out.
git sparse-checkout list

# Disable sparse checkout and check out everything again.
git sparse-checkout disable
```

### Clone With Sparse Checkout

```bash
# Partial clone plus sparse checkout for huge repositories.
git clone --filter=blob:none --sparse https://github.com/org/monorepo.git
cd monorepo
git sparse-checkout set packages/my-service

# No-checkout clone for metadata first.
git clone --no-checkout https://github.com/org/monorepo.git
cd monorepo
git sparse-checkout set packages/my-service
git checkout main
```

## Conflict Resolution

### Understand Conflict Markers

```text
<<<<<<< HEAD (or "ours")
Your changes on the current branch
=======
Their changes from the incoming branch
>>>>>>> feature-branch (or "theirs")
```

### Resolution Strategies

```bash
# Accept all of ours: current branch wins for this file.
git checkout --ours path/to/file.ts
git add path/to/file.ts

# Accept all of theirs: incoming branch wins for this file.
git checkout --theirs path/to/file.ts
git add path/to/file.ts

# Accept ours for all conflicted files.
git checkout --ours .
git add .

# Use a merge tool.
git mergetool

# See the three-way diff: base, ours, theirs.
git diff --cc path/to/file.ts

# Show common ancestor version.
git show :1:path/to/file.ts

# Show ours.
git show :2:path/to/file.ts

# Show theirs.
git show :3:path/to/file.ts
```

### Rebase Conflict Workflow

```bash
# During rebase, conflicts appear one commit at a time.
# Fix the conflict in the file, then stage it.
git add fixed-file.ts

# Continue to the next commit.
git rebase --continue

# If a commit is now empty after resolution, skip it.
git rebase --skip
```

### Rerere

`rerere` reuses recorded conflict resolutions.

```bash
# Enable rerere globally.
git config --global rerere.enabled true

# See recorded resolutions.
ls .git/rr-cache/

# Forget a bad resolution.
git rerere forget path/to/file.ts
```
