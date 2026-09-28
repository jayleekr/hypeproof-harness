#!/usr/bin/env bash
# check.sh — report vendor drift in the REAL consumer repositories.
#
# tests/run.sh and the `gate` CI job vendor into freshly created mock repos, so
# they prove sync.sh works but can never see how far the real consumers have
# fallen behind. That blind spot let skill-creator and notify sit four months
# stale in every consumer while CI stayed green (#208).
#
# Usage:
#   check.sh [--workspace DIR]
#
# Clones each consumer from tests/consumers.txt into DIR (default: a temp dir)
# and runs `sync.sh --check` against those real checkouts.
#
# Reachability is reported, never assumed:
#   • public repos clone anonymously
#   • private repos need a token in GH_TOKEN / GITHUB_TOKEN with read access
#   • a consumer that cannot be cloned is UNREACHABLE, not OK
#
# Exit codes:
#   0  every consumer reachable and no drift
#   1  drift detected in at least one reachable consumer
#   2  at least one consumer unreachable (coverage is incomplete)
#   3  usage / environment error
#
# Exit 2 outranks 0 but not 1: unknown coverage must never read as a pass.

set -uo pipefail

HARNESS_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$HARNESS_ROOT" || exit 3

OWNER="${CONSUMER_OWNER:-jayleekr}"
# Clone base, overridable so the behaviour can be exercised against local
# fixtures instead of the network.
GIT_BASE="${CONSUMER_GIT_BASE:-https://github.com/$OWNER}"
WORKSPACE=""
case "${1:-}" in
  --workspace)
    WORKSPACE="${2:-}"
    [ -n "$WORKSPACE" ] || { echo "--workspace needs a directory" >&2; exit 3; }
    ;;
  --help|-h)
    sed -n '/^# /{s/^# \{0,1\}//;p;}; /^[^#]/q' "$0"; exit 0 ;;
  "") : ;;
  *) echo "unknown arg: $1" >&2; exit 3 ;;
esac

if [ -z "$WORKSPACE" ]; then
  WORKSPACE="$(mktemp -d)"
  trap 'rm -rf "$WORKSPACE"' EXIT
fi
mkdir -p "$WORKSPACE" || exit 3

CONSUMERS_FILE="tests/consumers.txt"
[ -f "tests/consumers.local.txt" ] && CONSUMERS_FILE="tests/consumers.local.txt"

names=()
while IFS= read -r line; do
  line="${line%%#*}"
  line="$(printf '%s' "$line" | tr -d '[:space:]')"
  [ -z "$line" ] && continue
  names+=("${line##*/}")
done < "$CONSUMERS_FILE"

if [ "${#names[@]}" -eq 0 ]; then
  echo "no consumers listed in $CONSUMERS_FILE" >&2
  exit 3
fi

TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
unreachable=()
reachable=()

for name in "${names[@]}"; do
  dest="$WORKSPACE/$name"
  [ -d "$dest" ] && rm -rf "$dest"

  url="$GIT_BASE/$name.git"
  if [ -n "$TOKEN" ] && [ "${GIT_BASE#https://github.com}" != "$GIT_BASE" ]; then
    url="https://x-access-token:${TOKEN}@github.com/$OWNER/$name.git"
  fi

  if git clone --quiet --depth 1 "$url" "$dest" 2>/dev/null; then
    reachable+=("$name")
    echo "CLONED       $name"
  else
    unreachable+=("$name")
    # Never print the URL: it may carry the token.
    echo "UNREACHABLE  $name (private, or the token cannot read it)"
  fi
done

if [ "${#reachable[@]}" -eq 0 ]; then
  echo ""
  echo "✗ no consumer could be cloned — this run proves nothing" >&2
  exit 2
fi

# sync.sh reads the consumer list from the repository, so rather than rewriting
# that file we point it at a workspace holding only the clones we managed to
# make. Consumers we could not clone are simply absent there; sync.sh reports
# them as skipped, and we classify them from our own list instead — an
# unreachable consumer must never be counted as checked.
echo ""
report="$WORKSPACE/.check-output"
HYPEPROOF_WORKSPACE="$WORKSPACE" bash scripts/sync.sh --check 2>&1 | tee "$report"

# Drift is decided by the findings themselves, not by sync.sh's exit code,
# which also turns non-zero merely because the unreachable consumers are absent.
drift=0
grep -qE '^(DRIFT|EXTRA)' "$report" && drift=1

echo ""
echo "checked:     ${reachable[*]}"
if [ "${#unreachable[@]}" -gt 0 ]; then
  echo "NOT checked: ${unreachable[*]}"
fi

if [ "$drift" -ne 0 ]; then
  echo "✗ drift detected in a real consumer" >&2
  exit 1
fi
if [ "${#unreachable[@]}" -gt 0 ]; then
  echo "△ no drift in the consumers that could be read, but coverage is incomplete" >&2
  exit 2
fi
echo "✓ every consumer reachable and current"
exit 0
