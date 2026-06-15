#!/usr/bin/env bash
# register-skills.sh — keep harness-local skill registration in sync with skills/.
#
# Every canonical skill in skills/<name>/ must be discoverable by Claude Code in
# THIS repo through a .claude/skills/<name> symlink -> ../../skills/<name>. That
# symlink is derived state: it is fully determined by the contents of skills/, so
# nobody should have to remember to author it by hand. (Forgetting that manual
# step is exactly how #28 shipped skills/hype-review/ with no symlink.)
#
# This script generates the symlinks so registration is a deterministic function
# of skills/, and offers a read-only --check used by CI (lint job + T-V12) and
# the optional .githooks/pre-commit mirror.
#
# Modes:
#   (default)  apply  — create/fix symlinks; remove orphaned harness symlinks
#   --check           — report drift only, make no changes, exit 1 on any drift
#
set -euo pipefail

HARNESS_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HARNESS_ROOT"

MODE="apply"
case "${1:-}" in
  --check)   MODE="check" ;;
  --help|-h) sed -n '/^# /{s/^# \{0,1\}//;p;}; /^[^#]/q' "$0"; exit 0 ;;
  "")        : ;;
  *)         echo "unknown arg: $1" >&2; exit 2 ;;
esac

SKILLS_DIR="skills"
DEST_DIR=".claude/skills"
PREFIX="../../skills"   # relative target from inside .claude/skills/

[ "$MODE" = "apply" ] && [ ! -d "$DEST_DIR" ] && mkdir -p "$DEST_DIR"

drift=0

# 1. Every skills/<name>/ must have a correct, resolvable symlink.
for src in "$SKILLS_DIR"/*/; do
  [ -d "$src" ] || continue
  name="$(basename "$src")"
  link="$DEST_DIR/$name"
  want="$PREFIX/$name"
  if [ -L "$link" ] && [ "$(readlink "$link")" = "$want" ] && [ -e "$link" ]; then
    continue
  fi
  drift=1
  if [ "$MODE" = "check" ]; then
    if [ -L "$link" ]; then
      echo "DRIFT  wrong symlink: $link -> $(readlink "$link") (want $want)"
    elif [ -e "$link" ]; then
      echo "DRIFT  not a symlink: $link (want $want)"
    else
      echo "DRIFT  missing symlink: $link -> $want"
    fi
  else
    rm -rf "$link"
    ln -s "$want" "$link"
    echo "FIXED  $link -> $want"
  fi
done

# 2. No orphaned harness symlinks: a link into ../../skills/ whose target is gone.
#    Only links this script manages (PREFIX target) are touched.
if [ -d "$DEST_DIR" ]; then
  for link in "$DEST_DIR"/*; do
    [ -L "$link" ] || continue
    target="$(readlink "$link")"
    case "$target" in "$PREFIX"/*) ;; *) continue ;; esac
    name="$(basename "$link")"
    [ -d "$SKILLS_DIR/$name" ] && continue
    drift=1
    if [ "$MODE" = "check" ]; then
      echo "DRIFT  orphan symlink: $link -> $target (no $SKILLS_DIR/$name)"
    else
      rm -f "$link"
      echo "FIXED  removed orphan: $link"
    fi
  done
fi

if [ "$MODE" = "check" ]; then
  if [ "$drift" -ne 0 ]; then
    echo "✗ skill registration drift — run: scripts/register-skills.sh && git add .claude/skills" >&2
    exit 1
  fi
  echo "✓ skill registration in sync"
else
  echo "✓ skill registration applied"
fi
