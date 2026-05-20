# Rollback — vendor → submodule

Concrete procedure to revert a consumer repo from the vendored
skill-creator back to the original `.harness` submodule + symlink
architecture. Tested against each of the three consumers; estimated
time ~5 minutes per consumer.

> **Why a runbook**: `git revert <migration-commit>` alone is **not
> sufficient**. Revert restores `.gitmodules` and removes the real
> files but does **not** repopulate the `.harness/` clone (which
> revert removed as a gitlink). You will be left with a `.gitmodules`
> referencing a missing directory and a broken symlink. The steps
> below cover the full restore.

## Prerequisites

- You can push to the consumer repo's `main` (or open a PR).
- You have read access to `jayleekr/hypeproof-harness`.
- `gh` CLI authenticated.

## Steps (per consumer)

Replace `<consumer>` with one of: `hypeproof-studio` · `sediment` ·
`hypeprooflab`. The consumer's pre-migration submodule pin to restore
is documented in the migration PR description; if unknown, the latest
`hypeproof-harness` HEAD also works.

### 1. Identify the migration commit to revert

```bash
cd ~/CodeWorkspace/<consumer>
git log --oneline | grep -i 'vendor\|skill-creator' | head -5
# Find the commit subject like "chore: vendor skill-creator (drop .harness submodule)"
MIGRATION_SHA=<paste sha>
```

### 2. Branch off main

```bash
git switch main && git pull --ff-only
git switch -c chore/rollback-to-submodule
```

### 3. Revert the migration commit (restores `.gitmodules` + removes real files)

```bash
git revert --no-edit "$MIGRATION_SHA"
```

This re-adds the `.gitmodules` entry for `.harness` and removes the
vendored `.claude/skills/skill-creator/` real files. It does **not**
clone the submodule.

### 4. Repopulate the submodule

```bash
git submodule update --init .harness
```

Verify `.harness/skills/skill-creator/SKILL.md` exists and resolves.

### 5. Re-create the symlink

The revert restored a regular-file symlink commit, but if it didn't (or
if revert was clean only), force a real symlink in `.claude/skills/`.
**Use the repo-root–anchored relative path** so it works correctly in
both regular clones and worktrees (the `repos` worktree consumer has a
deeper directory layout where a naive `../../` would resolve wrong):

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
TARGET="$REPO_ROOT/.harness/skills/skill-creator"
LINK="$REPO_ROOT/.claude/skills/skill-creator"
if [ ! -L "$LINK" ]; then
  rm -rf "$LINK"
  # Compute correct relative path from $LINK's parent dir to $TARGET
  cd "$(dirname "$LINK")"
  REL="$(python3 -c "import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))" \
    "$TARGET" "$(pwd)")"
  ln -s "$REL" "$(basename "$LINK")"
  cd - >/dev/null
fi
git add .claude/skills/skill-creator .gitmodules .harness
```

> Why: for `hypeproof-studio` and `sediment`, `.claude/skills/` is two
> levels below the repo root, so `../../.harness/...` works. For the
> `hypeprooflab` worktree at `~/CodeWorkspace/hypeproof/.claude/worktrees/repos`,
> the symlink lives at `repos/.claude/skills/` and `.harness` is at
> `repos/.harness` — but `../../` from `repos/.claude/skills/` resolves
> two levels up the **filesystem** to `hypeproof/`, NOT to `repos/`.
> Using `git rev-parse --show-toplevel` + `os.path.relpath` produces
> the correct relative path in all cases.

### 6. Commit and push

```bash
git commit -m "chore: rollback to .harness submodule architecture"
git push -u origin chore/rollback-to-submodule
gh pr create --fill --base main
# Merge when ready
```

### 7. Verify

After merge on `main`:

```bash
git switch main && git pull
git submodule status .harness        # should show pinned SHA
readlink .claude/skills/skill-creator  # should print ../../.harness/skills/skill-creator
[ -f .claude/skills/skill-creator/SKILL.md ] && echo "✓ skill resolves"
```

## Rollback across all three consumers

Repeat steps 1–7 in each repo. Order does not matter; the consumers are
independent. Total rollback time ~15 minutes for all three.

The harness repo itself does **not** need rollback — `skills/skill-creator/`
is the canonical source in both architectures.

## Known gotchas

- **`.harness` submodule perms**: after rollback, members need read
  access to `jayleekr/hypeproof-harness` again. The five collaborator
  invitations sent at the vendor-migration time can stay (idempotent);
  if they were revoked, re-invite per harness `README.md` §7.
- **Lab worktree**: the hypeprooflab worktree at
  `~/CodeWorkspace/hypeproof/.claude/worktrees/repos` shares `.git`
  with the main clone. After the lab rollback PR merges, the worktree
  may need `git submodule update --init .harness` independently from
  the main clone (each worktree has its own submodule checkout).
- **Studio `vscodium-base` submodule**: untouched by this rollback.
  Don't accidentally `git submodule deinit --all`.
