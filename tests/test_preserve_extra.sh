#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
# Never read a developer's consumers.local.txt or modify real source/consumers.
mkdir -p "$TMP/harness"
git -C "$ROOT" archive HEAD | tar -x -C "$TMP/harness"
cp "$ROOT/scripts/sync.sh" "$TMP/harness/scripts/sync.sh"
HARNESS="$TMP/harness"
git -C "$HARNESS" init -q -b main
git -C "$HARNESS" -c user.email=ci@example.invalid -c user.name=CI add .
git -C "$HARNESS" -c user.email=ci@example.invalid -c user.name=CI commit -q -m fixture
for name in hypeproof-studio sediment hypeprooflab; do
  mkdir -p "$TMP/$name"
  git -C "$TMP/$name" init -q -b main
  git -C "$TMP/$name" config user.email ci@example.invalid
  git -C "$TMP/$name" config user.name CI
  git -C "$TMP/$name" commit --allow-empty -q -m init
done
sync_fixture() { HYPEPROOF_WORKSPACE="$TMP" bash "$HARNESS/scripts/sync.sh" "$@"; }
fail_sync() {
  local expected="$1"; shift
  if sync_fixture "$@" > "$TMP/check.log" 2>&1; then echo "unexpected success: $*" >&2; exit 1; fi
  grep -F "$expected" "$TMP/check.log" >/dev/null
}
printf 'old canonical\n' > "$HARNESS/scripts/notify/retired.txt"
printf 'old skill\n' > "$HARNESS/skills/hype-pr/retired.txt"
sync_fixture >/dev/null
lab="$TMP/hypeprooflab"
extra="$lab/scripts/notify/custom/local.txt"
skill_extra="$lab/.claude/skills/hype-pr/local.txt"
mkdir -p "$(dirname "$extra")"
printf 'keep these exact bytes\n' > "$extra"
printf 'keep skill bytes\n' > "$skill_extra"
fail_sync 'EXTRA' --check
fail_sync 'EXTRA' --check --preserve-extra
printf '%s\n' '# Explicit consumer-owned files' 'scripts/notify/custom/local.txt' '.claude/skills/hype-pr/local.txt' > "$lab/.harness-preserve"
sync_fixture --check --preserve-extra > "$TMP/listed.log"
grep -F 'local.txt (preserved)' "$TMP/listed.log" >/dev/null
cp "$extra" "$TMP/expected-extra"
cp "$skill_extra" "$TMP/expected-skill"
sync_fixture --preserve-extra >/dev/null
cmp "$extra" "$TMP/expected-extra"
cmp "$skill_extra" "$TMP/expected-skill"
# Previously canonical files cannot silently turn into consumer-owned extras.
rm "$HARNESS/scripts/notify/retired.txt" "$HARNESS/skills/hype-pr/retired.txt"
fail_sync 'EXTRA' --check --preserve-extra
grep -F 'scripts/notify/retired.txt' "$TMP/check.log" >/dev/null
grep -F 'hype-pr/retired.txt' "$TMP/check.log" >/dev/null
fail_sync 'ABORT' --preserve-extra
cmp "$extra" "$TMP/expected-extra"
# Remove only fixture retirement artifacts, then exercise commit mode.
for name in hypeproof-studio sediment hypeprooflab; do
  rm "$TMP/$name/scripts/notify/retired.txt" "$TMP/$name/.claude/skills/hype-pr/retired.txt"
  git -C "$TMP/$name" add .
  git -C "$TMP/$name" commit -q -m baseline
done
printf '\n# New canonical content\n' >> "$HARNESS/scripts/notify/README.md"
printf 'new canonical file\n' > "$HARNESS/scripts/notify/new-canonical.txt"
sync_fixture --commit --preserve-extra >/dev/null
cmp "$extra" "$TMP/expected-extra"
cmp "$skill_extra" "$TMP/expected-skill"
test -z "$(git -C "$lab" status --porcelain)"
git -C "$lab" ls-files --error-unmatch scripts/notify/new-canonical.txt >/dev/null
sync_fixture --check --preserve-extra >/dev/null
printf 'drift\n' >> "$lab/docs/AGENT-GUIDE.ko.md"
fail_sync 'DRIFT' --check --preserve-extra
cp "$HARNESS/docs/AGENT-GUIDE.ko.md" "$lab/docs/AGENT-GUIDE.ko.md"
# Invalid ownership declarations fail before any consumer is modified.
cp "$lab/.harness-preserve" "$TMP/good-manifest"
for bad in '../outside' '/absolute' 'scripts/notify/*' 'scripts/notify/custom' 'scripts/notify/README.md' 'scripts/notify/../outside' 'scripts/notify/HARNESS_VERSION'; do
  printf '%s\n' "$bad" > "$lab/.harness-preserve"
  fail_sync 'ABORT' --check --preserve-extra
  fail_sync 'ABORT' --preserve-extra
done
ln -s "$TMP/expected-extra" "$lab/scripts/notify/link.txt"
printf 'scripts/notify/link.txt\n' > "$lab/.harness-preserve"
fail_sync 'symlink' --preserve-extra
rm "$lab/scripts/notify/link.txt"
ln -s "$TMP" "$lab/scripts/notify/link-dir"
printf 'scripts/notify/link-dir/expected-extra\n' > "$lab/.harness-preserve"
fail_sync 'symlink' --check --preserve-extra
rm "$lab/scripts/notify/link-dir"
cp "$TMP/good-manifest" "$lab/.harness-preserve"
for mode in --check --commit ''; do
  for flags in '--force-delete --preserve-extra' '--preserve-extra --force-delete'; do
    # These are fixed test literals, never user-provided shell input.
    read -r -a args <<< "$mode $flags"
    fail_sync 'mutually exclusive' "${args[@]}"
  done
done
sync_fixture --check --preserve-extra >/dev/null
printf 'PASS explicit preservation: skills/scripts, retirement, bytes, commit, drift, invalid paths, symlinks, and flag combinations\n'
