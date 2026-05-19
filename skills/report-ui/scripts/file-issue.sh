#!/usr/bin/env bash
# Assemble a solver-ready issue body, attach evidence, and create the issue.
#
# Usage:
#   file-issue.sh --type feature|ux|bug --title "..." --narrative <file.md> \
#                 [--screenshot <png>]
#
# - Embeds the env JSON (scripts/collect-studio-env.sh) between machine markers
#   so a downstream solver skill can parse it (see references/solver-contract.md).
# - Screenshot is pushed to the orphan `contrib-evidence` branch (stays out of
#   main history, respects private-repo access control) and embedded by URL.
#   If that fails, the screenshot path is printed for manual drag-and-drop.
set -euo pipefail

REPO_SLUG="jayleekr/hypeproof-studio"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"

TYPE="" TITLE="" NARRATIVE="" SHOT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --type) TYPE="$2"; shift 2;;
    --title) TITLE="$2"; shift 2;;
    --narrative) NARRATIVE="$2"; shift 2;;
    --screenshot) SHOT="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done
[[ "$TYPE" =~ ^(feature|ux|bug)$ ]] || { echo "ERR --type must be feature|ux|bug" >&2; exit 2; }
[[ -n "$TITLE" && -f "$NARRATIVE" ]] || { echo "ERR need --title and --narrative <file>" >&2; exit 2; }

SLUG="$(date +%Y%m%d-%H%M%S)-$TYPE"
ENV_JSON="$(bash "$ROOT/scripts/collect-studio-env.sh" 2>/dev/null || echo '{"schema":"hps-env/1","error":"collector failed"}')"

# --- Evidence upload (best effort) -------------------------------------------
EVIDENCE_MD="_No screenshot attached._"
if [[ -n "$SHOT" && -s "$SHOT" ]]; then
  EVIDENCE_MD="⚠️ Screenshot saved locally at \`$SHOT\` — drag it into this issue."
  WT="$(mktemp -d)"
  if (
    set -e
    git -C "$ROOT" fetch -q origin contrib-evidence 2>/dev/null || true
    if git -C "$ROOT" show-ref -q refs/remotes/origin/contrib-evidence; then
      git -C "$ROOT" worktree add -q "$WT" origin/contrib-evidence
      git -C "$WT" checkout -q -B contrib-evidence
    else
      git -C "$ROOT" worktree add -q --detach "$WT"
      git -C "$WT" checkout -q --orphan contrib-evidence
      git -C "$WT" reset -q --hard
      git -C "$WT" clean -qfdx
    fi
    mkdir -p "$WT/evidence"
    cp "$SHOT" "$WT/evidence/$SLUG.png"
    git -C "$WT" add "evidence/$SLUG.png"
    git -C "$WT" -c user.email=studio@hypeproof.ai -c user.name="HypeProof Studio" \
      commit -q -m "evidence: $SLUG"
    git -C "$WT" push -q origin contrib-evidence
  ) 2>/dev/null; then
    EVIDENCE_MD="![screenshot](https://github.com/$REPO_SLUG/blob/contrib-evidence/evidence/$SLUG.png?raw=true)"
  fi
  git -C "$ROOT" worktree remove --force "$WT" 2>/dev/null || true
  rm -rf "$WT"
fi

# --- Body --------------------------------------------------------------------
BODY="$(mktemp)"
{
  cat "$NARRATIVE"
  echo
  echo "## Environment"
  echo "<!-- HPS-ENV-START -->"
  echo '```json'
  echo "$ENV_JSON"
  echo '```'
  echo "<!-- HPS-ENV-END -->"
  echo
  echo "## Screenshot / evidence"
  echo "$EVIDENCE_MD"
  echo
  echo "<!-- HPS-SOLVER: type=$TYPE; slug=$SLUG; source=studio-ui -->"
} > "$BODY"

URL="$(gh issue create --repo "$REPO_SLUG" \
  --title "$TITLE" --body-file "$BODY" \
  --label "type:$TYPE" --label "source:studio-ui" --label "solver:ready")"

rm -f "$BODY" "$NARRATIVE"
echo "$URL"
