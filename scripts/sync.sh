#!/usr/bin/env bash
# sync.sh — vendor hypeproof-harness skills into consumer repos.
#
# Usage:
#   sync.sh                  apply: rsync canonical → each consumer (writes HARNESS_VERSION)
#   sync.sh --check          read-only diff; exits 1 if any consumer drifts
#   sync.sh --commit         apply + git stage/commit in each consumer (no push)
#   sync.sh --force-delete   in apply, accept rsync --delete of files only in consumer
#
# Consumers come from tests/consumers.txt (one path per line; ~ and ${VAR}
# expanded; nonexistent paths are SKIPPED with a non-zero overall exit).
# A path is overridable per-machine by setting CONSUMER_<basename> in env.
#
# --commit mode requires the consumer's working tree to be on `main` and clean
# (other than the skill path). Bypass with: ALLOW_ANY_BRANCH=1 sync.sh --commit
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
case "${1:-}" in
  --check)         MODE="check" ;;
  --commit)        MODE="commit" ;;
  --force-delete)  FORCE_DELETE=1 ;;
  --help|-h)
    sed -n '/^# /{s/^# \{0,1\}//;p;}; /^[^#]/q' "$0"; exit 0 ;;
  "") : ;;
  *) echo "unknown arg: $1" >&2; exit 2 ;;
esac
# Second-arg form: sync.sh --commit --force-delete (allowed)
[ "${2:-}" = "--force-delete" ] && FORCE_DELETE=1

SKILLS=(skill-creator)        # vendored to consumer/.claude/skills/<name>/
DOCS=(MEMBER-GUIDE.ko.md)     # vendored to consumer/docs/<file>; single files in harness/docs/

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
          [ -f "$SRC/$rel" ] || { echo "EXTRA  $CNAME/$S/$rel"; d=1; overall_drift=1; }
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
        [ -f "$SRC/$rel" ] || will_delete+=("$rel")
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

    # --- commit-mode pre-flight (CR-10) ---
    if [ "$MODE" = "commit" ]; then
      branch="$(git -C "$C" rev-parse --abbrev-ref HEAD)"
      if [ "$branch" != "main" ] && [ "${ALLOW_ANY_BRANCH:-0}" != "1" ]; then
        echo "ABORT  $CNAME on branch '$branch' (not main). Set ALLOW_ANY_BRANCH=1 to override." >&2
        exit 4
      fi
      # any tracked changes outside the skill path?
      stray="$(git -C "$C" status --porcelain | awk -v p=".claude/skills/$S" '$2!~ p {print}' | head -1)"
      if [ -n "$stray" ]; then
        echo "ABORT  $CNAME has unrelated changes staged/modified: $stray" >&2
        exit 5
      fi
    fi

    # --- apply ---
    mkdir -p "$DST"
    rsync -a --delete --exclude='HARNESS_VERSION' "$SRC/" "$DST/"
    echo "$HARNESS_SHA" > "$DST/HARNESS_VERSION"

    if [ "$MODE" = "commit" ]; then
      if git -C "$C" diff --quiet -- ".claude/skills/$S"; then
        echo "NOOP   $CNAME/$S (already current)"
      else
        git -C "$C" add ".claude/skills/$S"
        git -C "$C" commit -q -m "chore(skills): sync $S from hypeproof-harness@${HARNESS_SHA:0:7}"
        echo "COMMIT $CNAME/$S @ ${HARNESS_SHA:0:7}"
      fi
    else
      echo "SYNC   $CNAME/$S @ ${HARNESS_SHA:0:7}"
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
      if git -C "$C" diff --quiet -- "docs/$D"; then
        echo "NOOP   $CNAME/docs/$D (already current)"
      else
        git -C "$C" add "docs/$D"
        git -C "$C" commit -q -m "docs: sync $D from hypeproof-harness@${HARNESS_SHA:0:7}"
        echo "COMMIT $CNAME/docs/$D @ ${HARNESS_SHA:0:7}"
      fi
    else
      echo "SYNC   $CNAME/docs/$D @ ${HARNESS_SHA:0:7}"
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
