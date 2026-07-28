#!/usr/bin/env bash
# identity-assert.sh — fail-closed GitHub identity gate for autonomous jobs.
#
# WHAT / WHY
#   Every autonomous GitHub job must prove, BEFORE it does any GitHub write,
#   that it is running as the dedicated automation principal — not as Jay's
#   over-scoped human admin token. If it cannot prove that, it must NOT write.
#   This is a control gate, not infrastructure: it is the single check that
#   makes "no autonomous write as the human owner" enforceable.
#
# TWO MODES (selected by the HYPEPROOF_AUTOMATION_ACTOR env var)
#   enforce  (HYPEPROOF_AUTOMATION_ACTOR is set & non-empty):
#            expected principal = $HYPEPROOF_AUTOMATION_ACTOR.
#            actual != expected  -> exit 1 (FAIL CLOSED, caller must not write).
#            actual == expected  -> exit 0 (PASS).
#            actual UNKNOWN       -> exit 1 (cannot prove identity => deny).
#   warn     (HYPEPROOF_AUTOMATION_ACTOR unset/empty — the current default):
#            resolve the actual principal, log a warning that the dedicated
#            automation identity is not provisioned, and exit 0 (NOT blocked).
#            This keeps the live cron fleet — which today runs as `jayleekr` —
#            working until Jay provisions the token and flips on enforce mode
#            by exporting HYPEPROOF_AUTOMATION_ACTOR=hypeproof-automation.
#
# CONTROL INVARIANT
#   The gate always self-reports (to stderr): expected principal, actual
#   principal, mode, and decision. Green proves what it checked.
#
# SAFETY
#   Never prints a token value — only the resolved login name. Identity is the
#   real write-path principal, resolved via `gh api user --jq .login`.
#
# EXIT CODES
#   0  pass (enforce match) OR warn (allowed, not provisioned)
#   1  fail-closed (enforce mismatch, or identity unknown under enforce)
#   2  usage error
#
# USAGE
#   scripts/identity-assert.sh [--expect <login>] [--quiet]
#   Call it at the top of an autonomous job entrypoint; abort the job on non-0.

set -uo pipefail

PROG="identity-assert"
QUIET=0
EXPECT_OVERRIDE=""

# --- logging (all to stderr; stdout is reserved for the machine-readable line)
log()  { [[ "$QUIET" -eq 1 ]] && return 0; printf '[%s] %s\n' "$PROG" "$*" >&2; }
warn() { printf '[%s] WARN: %s\n' "$PROG" "$*" >&2; }
err()  { printf '[%s] ERROR: %s\n' "$PROG" "$*" >&2; }

usage() {
  sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-2}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --expect) shift; EXPECT_OVERRIDE="${1:-}";
              [[ -z "$EXPECT_OVERRIDE" ]] && { err "--expect needs a login"; exit 2; } ;;
    --quiet)  QUIET=1 ;;
    -h|--help) usage 0 ;;
    *) err "unknown arg: $1"; exit 2 ;;
  esac
  shift
done

# --- resolve the expected principal & mode --------------------------------
# enforce mode is keyed on HYPEPROOF_AUTOMATION_ACTOR being set. --expect is a
# test/override hook that also forces enforce (used by the control tests).
EXPECTED="${EXPECT_OVERRIDE:-${HYPEPROOF_AUTOMATION_ACTOR:-}}"
if [[ -n "$EXPECTED" ]]; then
  MODE="enforce"
else
  MODE="warn"
fi

# --- resolve the ACTUAL active GitHub principal (never prints the token) ----
# ACTUAL_STATUS: ok | unknown  — "unknown" means gh is missing/unauthenticated
# or the API call failed, i.e. we could not prove who we are.
ACTUAL=""
ACTUAL_STATUS="unknown"
if command -v gh >/dev/null 2>&1; then
  # --jq keeps the token off the wire in our output; 2>/dev/null drops auth noise.
  if ACTUAL="$(gh api user --jq .login 2>/dev/null)" && [[ -n "$ACTUAL" ]]; then
    ACTUAL_STATUS="ok"
  fi
else
  err "gh CLI not found on PATH"
fi
[[ "$ACTUAL_STATUS" == "unknown" ]] && ACTUAL="<unknown>"

# --- decide ----------------------------------------------------------------
DECISION="fail"   # default-deny; only set to pass/warn on an explicit allow
if [[ "$MODE" == "warn" ]]; then
  DECISION="warn"
  warn "automation identity not provisioned; running as ${ACTUAL} (HYPEPROOF_AUTOMATION_ACTOR unset). GitHub writes NOT gated. Set HYPEPROOF_AUTOMATION_ACTOR to enforce."
else
  # enforce
  if [[ "$ACTUAL_STATUS" == "ok" && "$ACTUAL" == "$EXPECTED" ]]; then
    DECISION="pass"
  else
    DECISION="fail"
  fi
fi

# --- CONTROL INVARIANT self-report ----------------------------------------
# Human-readable to stderr...
log "control-invariant: expected=${EXPECTED:-<none>} actual=${ACTUAL} mode=${MODE} decision=${DECISION}"
# ...and one machine-readable line to stdout for callers/CI to capture.
printf 'identity-assert expected=%s actual=%s mode=%s decision=%s\n' \
  "${EXPECTED:-<none>}" "$ACTUAL" "$MODE" "$DECISION"

case "$DECISION" in
  pass) log "PASS: active principal matches the automation identity."; exit 0 ;;
  warn) exit 0 ;;
  fail)
    if [[ "$ACTUAL_STATUS" != "ok" ]]; then
      err "FAIL CLOSED: could not prove the active GitHub principal (enforce mode). Refusing GitHub writes."
    else
      err "FAIL CLOSED: active principal '${ACTUAL}' != expected '${EXPECTED}' (enforce mode). Refusing GitHub writes."
    fi
    exit 1 ;;
esac
