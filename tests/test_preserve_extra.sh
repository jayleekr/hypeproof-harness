#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

for name in hypeproof-studio sediment hypeprooflab; do
  mkdir -p "$TMP/$name"
  git -C "$TMP/$name" init -q -b main
  git -C "$TMP/$name" -c user.email=ci@example.com -c user.name=CI commit --allow-empty -q -m init
done

HYPEPROOF_WORKSPACE="$TMP" bash "$ROOT/scripts/sync.sh" --preserve-extra >/dev/null
extra="$TMP/hypeprooflab/scripts/notify/consumer-only.txt"
printf 'keep me\n' > "$extra"

if HYPEPROOF_WORKSPACE="$TMP" bash "$ROOT/scripts/sync.sh" --check >/dev/null 2>&1; then
  echo "default check accepted an extra file" >&2; exit 1
fi
HYPEPROOF_WORKSPACE="$TMP" bash "$ROOT/scripts/sync.sh" --check --preserve-extra > "$TMP/preserve-check.log"
grep -q 'EXTRA.*consumer-only.txt.*preserved' "$TMP/preserve-check.log"
HYPEPROOF_WORKSPACE="$TMP" bash "$ROOT/scripts/sync.sh" --preserve-extra >/dev/null
test "$(cat "$extra")" = "keep me"

printf 'drift\n' >> "$TMP/hypeprooflab/docs/AGENT-GUIDE.ko.md"
if HYPEPROOF_WORKSPACE="$TMP" bash "$ROOT/scripts/sync.sh" --check --preserve-extra >/dev/null 2>&1; then
  echo "preserve-extra hid canonical drift" >&2; exit 1
fi
