#!/usr/bin/env bash
# sync.sh — vendor hypeproof-harness skills into consumer repos.
#
# Usage:
#   sync.sh                  apply: rsync canonical → each consumer (writes HARNESS_VERSION)
#   sync.sh --check          read-only diff; exits 1 if any consumer drifts
#   sync.sh --commit         apply + git stage/commit in each consumer (no push)
#   sync.sh --force-delete   in apply, accept rsync --delete of files only in consumer
#   sync.sh --preserve-extra preserve only exact files listed in consumer/.harness-preserve
#
# Consumers come from tests/consumers.txt (one path per line; ~ and ${VAR}
# expanded; nonexistent paths are SKIPPED with a non-zero overall exit).
# A path is overridable per-machine by setting CONSUMER_<basename> in env.
#
# Apply and --commit check every consumer before writing to any of them. A
# consumer with an `origin` remote is fetched and must be on `main` exactly at
# origin/main (or already on its sync/harness-<sha7> branch built on it). There
# must be no changes outside the vendored paths. Sync then switches it to a
# fresh sync/harness-<sha7> branch cut from origin/main, and writes (and, with
# --commit, commits) there, ready for a PR. Any failed check aborts the whole
# run and prints the reason and the command that fixes it.
# A git repo without `origin` (local mocks) is applied in place; one on a branch
# other than main is refused for --commit.
# ALLOW_ANY_BRANCH=1 applies in place on whatever branch is checked out (no
# branch switch). A consumer behind origin/main is still refused.
#
# Identity used for --commit comes from the consumer repo's own git config;
# this script never overrides user.name/user.email.

set -euo pipefail

HARNESS_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HARNESS_ROOT"

# Workspace base for ${HYPEPROOF_WORKSPACE} entries in tests/consumers.txt.
# Default to the parent of the MAIN checkout, so consumers cloned as siblings
# of hypeproof-harness resolve with zero config — even when this script is
# invoked from a linked git worktree (where HARNESS_ROOT/.. would otherwise
# point at .git/worktrees/ or .claude/worktrees/, not the user workspace).
# Override by exporting the var.
if [ -z "${HYPEPROOF_WORKSPACE:-}" ]; then
  _common_dir="$(git -C "$HARNESS_ROOT" rev-parse --git-common-dir 2>/dev/null || true)"
  if [ -n "$_common_dir" ]; then
    case "$_common_dir" in
      /*) ;;
      *)  _common_dir="$HARNESS_ROOT/$_common_dir" ;;
    esac
    HYPEPROOF_WORKSPACE="$(cd "$_common_dir/../.." && pwd)"
  else
    HYPEPROOF_WORKSPACE="$(cd "$HARNESS_ROOT/.." && pwd)"
  fi
  unset _common_dir
fi

MODE="apply"
FORCE_DELETE=0
PRESERVE_EXTRA=0
for arg in "$@"; do
  case "$arg" in
    --check)          MODE="check" ;;
    --commit)         MODE="commit" ;;
    --force-delete)   FORCE_DELETE=1 ;;
    --preserve-extra) PRESERVE_EXTRA=1 ;;
    --help|-h)
      sed -n '/^# /{s/^# \{0,1\}//;p;}; /^[^#]/q' "$0"; exit 0 ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done
[ "$FORCE_DELETE" -eq 0 ] || [ "$PRESERVE_EXTRA" -eq 0 ] || {
  echo "--force-delete and --preserve-extra are mutually exclusive" >&2; exit 2;
}

SKILLS=(skill-creator hype-review weekly-loop hype-pr hype-deliver hype-align hype-verify hype-intent hype-studio hype-chalk hype-coordinate hypeproof-operator) # vendored to consumer/.claude/skills/<name>/
DOCS=(MEMBER-GUIDE.ko.md AGENT-GUIDE.ko.md DOCS-CONTRACT.ko.md HYPE-REVIEW.ko.md HYPE-PR.ko.md WEEKLY-LOOP.ko.md FIVE-SESSION-DELIVERY.ko.md WORK-DISCOVERY.ko.md) # vendored to consumer/docs/<file>
SCRIPTS=(notify docs-harness hype-review hype-pr weekly-harness) # vendored to consumer/scripts/<name>/ — directory trees from harness/scripts/<name>/
# Individual files vendored into consumer/scripts/<path>. Use this instead of
# SCRIPTS when harness ships only a file or two into a directory the consumer
# also keeps its own files in: SCRIPTS claims the whole tree with rsync
# --delete, which aborts the sync for that consumer (#209).
SCRIPT_FILES=(security/check-secrets.sh)
ROOT_AGENT_FILES=(CLAUDE.md AGENTS.md OPENCLAW.md) # vendored to consumer repo root

# --- consumer resolution ---
expand_path() {
  # tilde + ${VAR} expansion; defends against eval injection by stripping non-path chars
  local p="$1"
  # only allow safe chars before eval
  case "$p" in *[\'\"\`\$\(\)\;\|\&]*)
    if [[ "$p" != *'${'*'}'* ]] && [[ "$p" != '~'* ]]; then
      echo "$p"; return
    fi ;;
  esac
  eval "echo $p"
}
get_override() {
  local name="$1"
  # CONSUMER_<basename> env override; dashes are normalized to underscores
  # because POSIX env var names can't contain dashes
  local sanitized="${name//-/_}"
  local var="CONSUMER_${sanitized}"
  echo "${!var:-}"
}

# Per-machine override: tests/consumers.local.txt (gitignored) wins over
# tests/consumers.txt if present. Same syntax. Members typically list only
# the consumers they have cloned locally; the .example file ships in-tree.
CONSUMERS_FILE="tests/consumers.txt"
if [ -f "tests/consumers.local.txt" ]; then
  CONSUMERS_FILE="tests/consumers.local.txt"
  echo "Using local consumer list: $CONSUMERS_FILE" >&2
fi

CONSUMERS=()
while IFS= read -r raw; do
  raw="${raw%%#*}"; raw="${raw#"${raw%%[![:space:]]*}"}"; raw="${raw%"${raw##*[![:space:]]}"}"
  [ -z "$raw" ] && continue
  expanded="$(expand_path "$raw")"
  bn="$(basename "$expanded")"
  ovr="$(get_override "$bn")"
  [ -n "$ovr" ] && expanded="$ovr"
  CONSUMERS+=("$expanded")
done < "$CONSUMERS_FILE"
[ "${#CONSUMERS[@]}" -gt 0 ] || { echo "no consumers in $CONSUMERS_FILE" >&2; exit 2; }

HARNESS_SHA="$(git rev-parse HEAD)"
SYNC_BRANCH="sync/harness-${HARNESS_SHA:0:7}"

# Preservation is an explicit file ownership declaration, never a directory glob.
# Reject ambiguous paths before any consumer is written. Canonical files cannot
# be excluded from updates by a consumer manifest.
PRESERVE_PATHS=()
load_preserve_manifest() {
  local consumer="$1" manifest="$1/.harness-preserve" line path source x parent matched
  PRESERVE_PATHS=()
  [ "$PRESERVE_EXTRA" -eq 1 ] || return 0
  [ ! -L "$manifest" ] || { echo "ABORT: preservation manifest must not be a symlink" >&2; return 2; }
  [ -e "$manifest" ] || return 0
  [ -f "$manifest" ] || { echo "ABORT: preservation manifest must be a regular file" >&2; return 2; }
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|\#*) continue ;; esac
    case "$line" in
      *[!a-zA-Z0-9_./-]*|/*|*/|*//*|HARNESS_VERSION|*/HARNESS_VERSION)
        echo "ABORT: preservation entries must be exact relative file paths" >&2; return 2 ;;
    esac
    case "/$line/" in */../*|*/./*) echo "ABORT: unsafe preservation path" >&2; return 2 ;; esac
    source=""; matched=0
    for x in "${SKILLS[@]}"; do
      case "$line" in ".claude/skills/$x/"*) source="$HARNESS_ROOT/skills/$x/${line#.claude/skills/$x/}"; matched=1 ;; esac
    done
    for x in "${SCRIPTS[@]}"; do
      case "$line" in "scripts/$x/"*) source="$HARNESS_ROOT/$line"; matched=1 ;; esac
    done
    [ "$matched" -eq 1 ] || { echo "ABORT: preservation path is outside a vendored tree" >&2; return 2; }
    [ ! -e "$source" ] && [ ! -L "$source" ] || { echo "ABORT: cannot preserve a canonical path" >&2; return 2; }
    path="$consumer/$line"; parent="$path"
    while [ "$parent" != "$consumer" ]; do
      [ ! -L "$parent" ] || { echo "ABORT: preservation path traverses a symlink" >&2; return 2; }
      parent="$(dirname "$parent")"
    done
    [ ! -e "$path" ] || [ -f "$path" ] || { echo "ABORT: preservation entry must name a regular file" >&2; return 2; }
    PRESERVE_PATHS+=("$line")
  done < "$manifest"
}
is_preserved() {
  local path="$1" entry
  for entry in "${PRESERVE_PATHS[@]:-}"; do [ "$path" = "$entry" ] && return 0; done
  return 1
}
# Build anchored rsync receiver-protection rules, while retaining --delete.
preserve_filters() {
  local prefix="$1" entry
  RSYNC_PRESERVE=(--delete)
  for entry in "${PRESERVE_PATHS[@]:-}"; do
    case "$entry" in "$prefix/"*) RSYNC_PRESERVE+=("--filter=P /${entry#"$prefix/"}") ;; esac
  done
}
for C in "${CONSUMERS[@]}"; do
  [ ! -d "$C" ] || load_preserve_manifest "$C"
done

# --- consumer pre-flight (apply / commit) ---
# Sync writes into whatever the consumer has checked out. A checkout far behind
# origin/main, or on a feature branch, turned into a working tree that was older
# than its own origin/main and mixed into unrelated work (studio 54 behind,
# sediment 8 behind, lab on a feature branch). So every consumer is checked
# before any of them is written, and writes land on a branch cut from
# origin/main rather than on whatever happens to be checked out.
is_vendored_path() {
  local p="$1" x
  for x in "${SKILLS[@]}";           do case "$p" in ".claude/skills/$x"|".claude/skills/$x/"*) return 0 ;; esac; done
  for x in "${SCRIPTS[@]:-}";        do [ -n "$x" ] && case "$p" in "scripts/$x"|"scripts/$x/"*) return 0 ;; esac; done
  for x in "${SCRIPT_FILES[@]:-}";   do
    # the file itself, plus the tree-era stamp that sync removes beside it
    [ -n "$x" ] && { [ "$p" = "scripts/$x" ] || [ "$p" = "$(dirname "scripts/$x")/HARNESS_VERSION" ]; } && return 0
  done
  for x in "${DOCS[@]:-}";           do [ "$p" = "docs/$x" ] && return 0; done
  for x in "${ROOT_AGENT_FILES[@]:-}"; do [ "$p" = "$x" ] && return 0; done
  return 1
}

# Echoes the first changed path outside the vendored paths, if any.
stray_change() {
  local C="$1" rec st p
  while IFS= read -r -d '' rec; do
    st="${rec:0:2}"; p="${rec:3}"
    is_vendored_path "$p" || { echo "$p"; return; }
    case "$st" in
      R*|C*) IFS= read -r -d '' p; is_vendored_path "$p" || { echo "$p"; return; } ;;
    esac
  done < <(git -C "$C" status --porcelain=v1 -z --untracked-files=all)
}

is_own_repo() {
  local C="$1" top
  top="$(git -C "$C" rev-parse --show-toplevel 2>/dev/null)" || return 1
  [ "$top" = "$(cd "$C" && pwd -P)" ]
}

preflight_abort() {
  echo "ABORT  $1 — $2" >&2
  echo "       fix: $3" >&2
  echo "       nothing was written to any consumer." >&2
  exit "$4"
}

# Per consumer: "inplace" or "branch" (switch to SYNC_BRANCH before writing).
PLAN=()
preflight_consumer() {
  local C="$1" CNAME branch stray behind ahead
  CNAME="$(basename "$C")"
  if ! is_own_repo "$C"; then
    # Not a git checkout of its own (a scratch directory): nothing to be
    # behind, nothing to commit into.
    [ "$MODE" = "commit" ] && preflight_abort "$CNAME" "not a git repository: $C" \
      "clone the consumer there, or drop it from $CONSUMERS_FILE" 4
    PLAN+=("inplace"); return
  fi
  # symbolic-ref also names an unborn branch; a detached HEAD reads as "HEAD".
  branch="$(git -C "$C" symbolic-ref --short -q HEAD || echo HEAD)"
  if git -C "$C" remote get-url origin >/dev/null 2>&1 || [ "$MODE" = "commit" ]; then
    stray="$(stray_change "$C")"
    [ -n "$stray" ] && preflight_abort "$CNAME" "has changes outside the vendored paths: $stray" \
      "commit or stash them first (git -C $C status)" 5
  fi

  if ! git -C "$C" remote get-url origin >/dev/null 2>&1; then
    # Local-only repo (CI and test mocks): no remote to fall behind, and apply
    # writes in place without switching branches.
    if [ "$MODE" = "commit" ] && [ "$branch" != "main" ] && [ "${ALLOW_ANY_BRANCH:-0}" != "1" ]; then
      preflight_abort "$CNAME" "on branch '$branch' (not main)" \
        "git -C $C switch main   (or ALLOW_ANY_BRANCH=1 to commit in place)" 4
    fi
    PLAN+=("inplace"); return
  fi

  git -C "$C" fetch -q origin main 2>/dev/null || preflight_abort "$CNAME" "cannot fetch origin/main" \
    "check network/credentials: git -C $C fetch origin main" 6
  behind="$(git -C "$C" rev-list --count HEAD..origin/main)"
  if [ "$behind" -gt 0 ]; then
    if [ "$branch" = "main" ]; then
      preflight_abort "$CNAME" "main is $behind commit(s) behind origin/main" \
        "git -C $C pull --ff-only" 4
    fi
    preflight_abort "$CNAME" "branch '$branch' is $behind commit(s) behind origin/main" \
      "git -C $C switch main && git -C $C pull --ff-only" 4
  fi

  if [ "${ALLOW_ANY_BRANCH:-0}" = "1" ]; then
    echo "WARN   $CNAME applying in place on '$branch' (ALLOW_ANY_BRANCH=1)" >&2
    PLAN+=("inplace"); return
  fi
  if [ "$branch" = "$SYNC_BRANCH" ]; then
    PLAN+=("inplace"); return    # re-run on the branch a previous sync created
  fi
  if [ "$branch" != "main" ]; then
    preflight_abort "$CNAME" "on branch '$branch' (not main); sync would mix into that work" \
      "git -C $C switch main && git -C $C pull --ff-only" 4
  fi
  ahead="$(git -C "$C" rev-list --count origin/main..HEAD)"
  [ "$ahead" -gt 0 ] && preflight_abort "$CNAME" "main has $ahead local commit(s) not on origin/main" \
    "move them to a branch, then: git -C $C reset --keep origin/main" 4
  git -C "$C" show-ref --verify --quiet "refs/heads/$SYNC_BRANCH" && preflight_abort "$CNAME" \
    "branch '$SYNC_BRANCH' already exists" \
    "git -C $C switch $SYNC_BRANCH   (or delete it: git -C $C branch -D $SYNC_BRANCH)" 4
  PLAN+=("branch")
}

if [ "$MODE" != "check" ]; then
  for C in "${CONSUMERS[@]}"; do
    if [ -d "$C" ]; then preflight_consumer "$C"; else PLAN+=("missing"); fi
  done
  i=0
  for C in "${CONSUMERS[@]}"; do
    if [ "${PLAN[$i]}" = "branch" ]; then
      git -C "$C" switch -q -c "$SYNC_BRANCH" origin/main
      echo "BRANCH $(basename "$C") → $SYNC_BRANCH (from origin/main)"
    fi
    i=$((i+1))
  done
fi

# --- main loop ---
overall_drift=0
skipped=0
found=0
for C in "${CONSUMERS[@]}"; do
  CNAME="$(basename "$C")"
  if [ ! -d "$C" ]; then
    echo "SKIP   $CNAME — path missing: $C" >&2
    skipped=$((skipped+1))
    continue
  fi
  found=$((found+1))
  load_preserve_manifest "$C"
  for S in "${SKILLS[@]}"; do
    SRC="$HARNESS_ROOT/skills/$S"
    DST="$C/.claude/skills/$S"
    [ -d "$SRC" ] || { echo "[!] missing source: $SRC" >&2; exit 2; }

    if [ "$MODE" = "check" ]; then
      d=0
      while IFS= read -r -d '' f; do
        rel="${f#$SRC/}"
        b="$DST/$rel"
        if [ ! -f "$b" ] || ! cmp -s "$f" "$b"; then
          echo "DRIFT  $CNAME/$S/$rel"; d=1; overall_drift=1
        fi
      done < <(find "$SRC" -type f -print0)
      if [ -d "$DST" ]; then
        while IFS= read -r -d '' f; do
          rel="${f#$DST/}"
          [ "$rel" = "HARNESS_VERSION" ] && continue
          if [ ! -f "$SRC/$rel" ]; then
            if is_preserved ".claude/skills/$S/$rel"; then
              echo "EXTRA  $CNAME/$S/$rel (preserved)"
            else
              echo "EXTRA  $CNAME/$S/$rel"
            fi
            if ! is_preserved ".claude/skills/$S/$rel"; then d=1; overall_drift=1; fi
          fi
        done < <(find "$DST" -type f -print0)
      fi
      [ "$d" -eq 0 ] && echo "OK     $CNAME/$S"
      continue
    fi

    # apply / commit modes
    # --- deletion preview (CR-8) ---
    will_delete=()
    if [ -d "$DST" ]; then
      while IFS= read -r -d '' f; do
        rel="${f#$DST/}"
        [ "$rel" = "HARNESS_VERSION" ] && continue
        [ -f "$SRC/$rel" ] || is_preserved ".claude/skills/$S/$rel" || will_delete+=("$rel")
      done < <(find "$DST" -type f -print0)
    fi
    if [ "${#will_delete[@]}" -gt 0 ]; then
      echo "   ⚠ $CNAME/$S — rsync --delete will remove:"
      for w in "${will_delete[@]}"; do echo "     - $w"; done
      if [ "$FORCE_DELETE" -ne 1 ]; then
        echo "   ABORT: refusing to delete consumer-side files without --force-delete." >&2
        exit 3
      fi
      echo "   (proceeding because --force-delete given)"
    fi

    # (branch / cleanliness checks ran once per consumer in the pre-flight)

    # --- apply ---
    mkdir -p "$DST"
    preserve_filters ".claude/skills/$S"
    rsync -a "${RSYNC_PRESERVE[@]}" --exclude='HARNESS_VERSION' "$SRC/" "$DST/"
    echo "$HARNESS_SHA" > "$DST/HARNESS_VERSION"

    if [ "$MODE" = "commit" ]; then
      # Stage first: a plain diff misses files that are new to the consumer.
      git -C "$C" add -A -- ".claude/skills/$S"
      if git -C "$C" diff --cached --quiet -- ".claude/skills/$S"; then
        echo "NOOP   $CNAME/$S (already current)"
      else
        git -C "$C" commit -q -m "chore(skills): sync $S from hypeproof-harness@${HARNESS_SHA:0:7}"
        echo "COMMIT $CNAME/$S @ ${HARNESS_SHA:0:7}"
      fi
    else
      echo "SYNC   $CNAME/$S @ ${HARNESS_SHA:0:7}"
    fi
  done

  # --- scripts vendoring (directory trees into consumer/scripts/<name>/) ---
  # Same pattern as SKILLS, but lands under scripts/ (not .claude/skills/).
  # Used for cross-product Python modules like notify/.
  for SC in "${SCRIPTS[@]:-}"; do
    [ -z "$SC" ] && continue
    SCSRC="$HARNESS_ROOT/scripts/$SC"
    SCDST="$C/scripts/$SC"
    [ -d "$SCSRC" ] || { echo "[!] missing script source: $SCSRC" >&2; continue; }

    if [ "$MODE" = "check" ]; then
      d=0
      while IFS= read -r -d '' f; do
        rel="${f#$SCSRC/}"
        b="$SCDST/$rel"
        if [ ! -f "$b" ] || ! cmp -s "$f" "$b"; then
          echo "DRIFT  $CNAME/scripts/$SC/$rel"; d=1; overall_drift=1
        fi
      done < <(find "$SCSRC" -type f -print0)
      if [ -d "$SCDST" ]; then
        while IFS= read -r -d '' f; do
          rel="${f#$SCDST/}"
          [ "$rel" = "HARNESS_VERSION" ] && continue
          if [ ! -f "$SCSRC/$rel" ]; then
            if is_preserved "scripts/$SC/$rel"; then
              echo "EXTRA  $CNAME/scripts/$SC/$rel (preserved)"
            else
              echo "EXTRA  $CNAME/scripts/$SC/$rel"
            fi
            if ! is_preserved "scripts/$SC/$rel"; then d=1; overall_drift=1; fi
          fi
        done < <(find "$SCDST" -type f -print0)
      fi
      [ "$d" -eq 0 ] && echo "OK     $CNAME/scripts/$SC"
      continue
    fi

    # deletion preview
    will_delete=()
    if [ -d "$SCDST" ]; then
      while IFS= read -r -d '' f; do
        rel="${f#$SCDST/}"
        [ "$rel" = "HARNESS_VERSION" ] && continue
        [ -f "$SCSRC/$rel" ] || is_preserved "scripts/$SC/$rel" || will_delete+=("$rel")
      done < <(find "$SCDST" -type f -print0)
    fi
    if [ "${#will_delete[@]}" -gt 0 ]; then
      echo "   ⚠ $CNAME/scripts/$SC — rsync --delete will remove:"
      for w in "${will_delete[@]}"; do echo "     - $w"; done
      if [ "$FORCE_DELETE" -ne 1 ]; then
        echo "   ABORT: refusing to delete consumer-side files without --force-delete." >&2
        exit 3
      fi
    fi

    mkdir -p "$SCDST"
    preserve_filters "scripts/$SC"
    rsync -a "${RSYNC_PRESERVE[@]}" --exclude='HARNESS_VERSION' "$SCSRC/" "$SCDST/"
    echo "$HARNESS_SHA" > "$SCDST/HARNESS_VERSION"

    if [ "$MODE" = "commit" ]; then
      # Stage first: a plain diff misses files that are new to the consumer.
      git -C "$C" add -A -- "scripts/$SC"
      if git -C "$C" diff --cached --quiet -- "scripts/$SC"; then
        echo "NOOP   $CNAME/scripts/$SC (already current)"
      else
        git -C "$C" commit -q -m "chore(scripts): sync $SC from hypeproof-harness@${HARNESS_SHA:0:7}"
        echo "COMMIT $CNAME/scripts/$SC @ ${HARNESS_SHA:0:7}"
      fi
    else
      echo "SYNC   $CNAME/scripts/$SC @ ${HARNESS_SHA:0:7}"
    fi
  done

  # --- script file vendoring (single files; the consumer owns the directory) ---
  # No --delete and no directory ownership: the consumer may keep its own files
  # next to these. A stale HARNESS_VERSION from when the path was vendored as a
  # tree is removed, because it no longer describes the directory.
  for SF in "${SCRIPT_FILES[@]:-}"; do
    [ -z "$SF" ] && continue
    SFSRC="$HARNESS_ROOT/scripts/$SF"
    SFDST="$C/scripts/$SF"
    SFDIR="$(dirname "scripts/$SF")"
    [ -f "$SFSRC" ] || { echo "[!] missing script file source: $SFSRC" >&2; continue; }

    if [ "$MODE" = "check" ]; then
      if [ ! -f "$SFDST" ] || ! cmp -s "$SFSRC" "$SFDST"; then
        echo "DRIFT  $CNAME/scripts/$SF"; overall_drift=1
      elif [ -f "$C/$SFDIR/HARNESS_VERSION" ]; then
        echo "DRIFT  $CNAME/$SFDIR/HARNESS_VERSION stale (path is file-vendored, not a tree)"; overall_drift=1
      else
        echo "OK     $CNAME/scripts/$SF"
      fi
      continue
    fi

    mkdir -p "$(dirname "$SFDST")"
    cp -p "$SFSRC" "$SFDST"
    stale="$C/$SFDIR/HARNESS_VERSION"
    if [ -f "$stale" ]; then
      rm -f "$stale"
      echo "   ↳ removed stale $CNAME/$SFDIR/HARNESS_VERSION (tree → file vendoring)"
    fi

    if [ "$MODE" = "commit" ]; then
      # Stage only what sync owns here; the rest of $SFDIR belongs to the consumer.
      git -C "$C" add -A -- "scripts/$SF"
      git -C "$C" rm -q --cached --ignore-unmatch -- "$SFDIR/HARNESS_VERSION"
      if git -C "$C" diff --cached --quiet -- "scripts/$SF" "$SFDIR/HARNESS_VERSION"; then
        echo "NOOP   $CNAME/scripts/$SF (already current)"
      else
        git -C "$C" commit -q -m "chore(scripts): sync $SF from hypeproof-harness@${HARNESS_SHA:0:7}"
        echo "COMMIT $CNAME/scripts/$SF @ ${HARNESS_SHA:0:7}"
      fi
    else
      echo "SYNC   $CNAME/scripts/$SF @ ${HARNESS_SHA:0:7}"
    fi
  done

  # --- docs vendoring (sidecar, single files into consumer/docs/) ---
  for D in "${DOCS[@]:-}"; do
    [ -z "$D" ] && continue
    DSRC="$HARNESS_ROOT/docs/$D"
    DDST="$C/docs/$D"
    [ -f "$DSRC" ] || { echo "[!] missing doc source: $DSRC" >&2; continue; }

    if [ "$MODE" = "check" ]; then
      if [ ! -f "$DDST" ] || ! cmp -s "$DSRC" "$DDST"; then
        echo "DRIFT  $CNAME/docs/$D"; overall_drift=1
      else
        echo "OK     $CNAME/docs/$D"
      fi
      continue
    fi

    mkdir -p "$(dirname "$DDST")"
    cp -p "$DSRC" "$DDST"

    if [ "$MODE" = "commit" ]; then
      # Stage first: a plain diff misses files that are new to the consumer.
      git -C "$C" add -A -- "docs/$D"
      if git -C "$C" diff --cached --quiet -- "docs/$D"; then
        echo "NOOP   $CNAME/docs/$D (already current)"
      else
        git -C "$C" commit -q -m "docs: sync $D from hypeproof-harness@${HARNESS_SHA:0:7}"
        echo "COMMIT $CNAME/docs/$D @ ${HARNESS_SHA:0:7}"
      fi
    else
      echo "SYNC   $CNAME/docs/$D @ ${HARNESS_SHA:0:7}"
    fi
  done

  # --- agent entrypoint seeding (single files into consumer repo root) ---
  # These files often carry repo-specific instructions. Seed a missing file
  # from harness, but never overwrite an existing consumer entrypoint.
  for F in "${ROOT_AGENT_FILES[@]:-}"; do
    [ -z "$F" ] && continue
    FSRC="$HARNESS_ROOT/$F"
    FDST="$C/$F"
    [ -f "$FSRC" ] || { echo "[!] missing agent entrypoint source: $FSRC" >&2; continue; }

    if [ "$MODE" = "check" ]; then
      if [ ! -f "$FDST" ]; then
        echo "DRIFT  $CNAME/$F"; overall_drift=1
      elif ! grep -q 'docs/AGENT-GUIDE\.ko\.md' "$FDST"; then
        echo "DRIFT  $CNAME/$F missing docs/AGENT-GUIDE.ko.md reference"; overall_drift=1
      else
        echo "OK     $CNAME/$F"
      fi
      continue
    fi

    if [ -f "$FDST" ]; then
      if grep -q 'docs/AGENT-GUIDE\.ko\.md' "$FDST"; then
        echo "NOOP   $CNAME/$F (consumer-specific entrypoint already references AGENT-GUIDE)"
      else
        echo "MANUAL $CNAME/$F exists but does not reference docs/AGENT-GUIDE.ko.md; preserving consumer file" >&2
      fi
      continue
    fi

    cp -p "$FSRC" "$FDST"

    if [ "$MODE" = "commit" ]; then
      # Stage first: a plain diff misses files that are new to the consumer.
      git -C "$C" add -A -- "$F"
      if git -C "$C" diff --cached --quiet -- "$F"; then
        echo "NOOP   $CNAME/$F (already current)"
      else
        git -C "$C" commit -q -m "docs(agents): sync $F from hypeproof-harness@${HARNESS_SHA:0:7}"
        echo "COMMIT $CNAME/$F @ ${HARNESS_SHA:0:7}"
      fi
    else
      echo "SYNC   $CNAME/$F @ ${HARNESS_SHA:0:7}"
    fi
  done
done

if [ "$found" -eq 0 ]; then
  {
    echo ""
    echo "✗ No consumer repos found — every path in tests/consumers.txt was missing."
    echo "  Resolve one of:"
    echo "    • clone consumers as siblings of hypeproof-harness (zero-config), or"
    echo "    • export HYPEPROOF_WORKSPACE=/abs/path/to/workspace, or"
    echo "    • set CONSUMER_<repo>=/abs/path per repo (e.g. CONSUMER_hypeproof_studio=...)."
    echo "  HYPEPROOF_WORKSPACE currently resolves to: $HYPEPROOF_WORKSPACE"
  } >&2
fi

if [ "$MODE" = "check" ]; then
  if [ "$overall_drift" -eq 0 ] && [ "$skipped" -eq 0 ]; then
    echo "✓ no drift"; exit 0
  elif [ "$overall_drift" -eq 0 ] && [ "$skipped" -gt 0 ]; then
    echo "△ no drift but $skipped consumer(s) skipped — partial pass" >&2; exit 1
  else
    echo "✗ drift detected" >&2; exit 1
  fi
fi

# apply/commit modes: also non-zero if any consumer was skipped
[ "$skipped" -eq 0 ]
