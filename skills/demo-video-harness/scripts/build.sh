#!/usr/bin/env bash
# End-to-end demo-video build: preflight -> lint -> capture -> tts -> assemble.
# Usage: ./build.sh timeline/<name>.yaml [--skip-capture]
set -e
cd "$(dirname "$0")/.."

TL="${1:?usage: build.sh timeline/<name>.yaml [--skip-capture]}"

if [ -z "${SKIP_PREFLIGHT:-}" ]; then
  bash scripts/preflight.sh "$TL"
  if [ $? -ne 0 ]; then
    echo "build: aborted by preflight (set SKIP_PREFLIGHT=1 to override)"
    exit 1
  fi
fi

echo "== lint =="
python3 scripts/lint.py "$TL"

if [ "${2:-}" != "--skip-capture" ]; then
  echo "== capture =="
  python3 scripts/capture.py "$TL"
fi

echo "== tts =="
python3 scripts/tts.py "$TL"

echo "== assemble =="
python3 scripts/assemble.py "$TL"

NAME=$(python3 -c "import yaml,sys; print(yaml.safe_load(open('$TL'))['video'])")
echo "== done: out/${NAME}.mp4 =="
cat "out/${NAME}-report.md"
