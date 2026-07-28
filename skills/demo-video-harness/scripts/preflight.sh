#!/usr/bin/env bash
# Self-onboarding preflight for the demo-video-harness skill.
# Checks every local dependency, prints the exact fix for anything missing,
# and (if a timeline path is given) does a best-effort reachability check
# against that timeline's base_url. Has no opinion about your app or infra
# beyond that — there is no bundled backend to reach.
#
# Usage: preflight.sh [timeline/<name>.yaml]
# Exit codes: 0 = all good, 1 = hard blocker (missing dependency).
set -u
HARD_FAIL=0

ok()   { echo "  [ok]   $1"; }
warn() { echo "  [warn] $1"; }
fail() { echo "  [FAIL] $1"; echo "         fix: $2"; HARD_FAIL=1; }

echo "== preflight: local tools =="
command -v python3 >/dev/null && ok "python3 ($(python3 -V 2>&1))" \
  || fail "python3 not found" "install Python 3.9+"
python3 -c "import yaml" 2>/dev/null && ok "pyyaml" \
  || fail "pyyaml missing" "pip install pyyaml"
python3 -c "import playwright" 2>/dev/null && ok "playwright (pip)" \
  || fail "playwright missing" "pip install playwright"
if [ -d "${HOME}/Library/Caches/ms-playwright" ] || [ -d "${HOME}/.cache/ms-playwright" ]; then
  ok "chromium browser"
else
  fail "playwright chromium not installed" "python3 -m playwright install chromium"
fi
if command -v ffmpeg >/dev/null; then
  if ffmpeg -hide_banner -encoders 2>/dev/null | grep -q libx264; then
    ok "ffmpeg (+libx264)"
  else
    fail "ffmpeg lacks libx264" "reinstall ffmpeg with libx264 support"
  fi
else
  fail "ffmpeg not found" "brew install ffmpeg (macOS) / apt install ffmpeg (Linux)"
fi
if command -v magick >/dev/null; then
  ok "imagemagick (QC contact sheet)"
else
  warn "imagemagick not found (optional — QC contact sheet will be skipped)"
fi

TL="${1:-}"
if [ -n "$TL" ] && [ -f "$TL" ]; then
  BASE_URL=$(python3 -c "
import sys, yaml
doc = yaml.safe_load(open(sys.argv[1]))
print(doc.get('base_url', ''))
" "$TL" 2>/dev/null)
  if [ -n "$BASE_URL" ]; then
    echo "== preflight: target app ($BASE_URL) =="
    if command -v curl >/dev/null && curl -sk -m 6 -o /dev/null "$BASE_URL"; then
      ok "$BASE_URL reachable"
    else
      warn "$BASE_URL not reachable from here — start your app or check the URL"
      warn "(cuts with capture.scene: instead of base_url need no network at all)"
    fi
  fi
fi

if [ "$HARD_FAIL" -ne 0 ]; then
  echo
  echo "preflight: BLOCKED (fix the [FAIL] items above)"
  exit 1
fi
echo
echo "preflight: OK"
exit 0
