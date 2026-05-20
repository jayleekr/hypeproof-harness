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

SKILLS=(skill-creator)  # extend as the harness grows

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
  # CONSUMER_<basename> env override (case-sensitive)
  local var="CONSUMER_${name}"
  echo "${!var:-}"
}

CONSUMERS=()
while IFS= read -r raw; do
  raw="${raw%%#*}"; raw="${raw#"${raw%%[![:space:]]*}"}"; raw="${raw%"${raw##*[![:space:]]}"}"
  [ -z "$raw" ] && continue
  expanded="$(expand_path "$raw")"
  bn="$(basename "$expanded")"
  ovr="$(get_override "$bn")"
  [ -n "$ovr" ] && expanded="$ovr"
  CONSUMERS+=("$expanded")
done < tests/consumers.txt
[ "${#CONSUMERS[@]:-0}" -gt 0 ] || { echo "no consumers in tests/consumers.txt" >&2; exit 2; }

HARNESS_SHA="$(git rev-parse HEAD)"

# --- main loop ---
overall_drift=0
skipped=0
for C in "${CONSUMERS[@]}"; do
  CNAME="$(basename "$C")"
  if [ ! -d "$C" ]; then
    echo "SKIP   $CNAME — path missing: $C" >&2
    skipped=$((skipped+1))
    continue
  fi
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
    if [ "${#will_delete[@]:-0}" -gt 0 ]; then
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
done

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
