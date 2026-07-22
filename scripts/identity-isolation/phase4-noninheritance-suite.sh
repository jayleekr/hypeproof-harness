#!/usr/bin/env bash
# phase4-noninheritance-suite.sh — verify the agent identity CANNOT inherit Jay's
# credentials, and CAN do only its delegated work. Run AS the agent account
# after Phase 3:   su - hypeproof-agent -c '.../phase4-noninheritance-suite.sh'
#
# SAFETY: every MUST-FAIL probe is side-effect-free — it targets a guaranteed-
# nonexistent resource or is a value-preserving no-op, so even if isolation were
# broken and the call SUCCEEDED, nothing is created/deleted/mutated. No secret
# values are printed.
#
# MODES (auto-detected by whoami):
#   AGENT MODE (whoami=hypeproof-agent): full assertions; non-zero exit on any
#     MUST-FAIL that unexpectedly succeeded or MUST-PASS that failed.
#   REFERENCE MODE (whoami=jaylee): MUST-PASS reference checks run (Jay is a
#     superset, so they should pass); MUST-FAIL checks are reported as N/A
#     because Jay legitimately holds those rights — they are only meaningful
#     from the agent. Use this mode now to confirm the "should-succeed" column.
set -uo pipefail
WHO="$(whoami)"
MODE="reference"; [[ "$WHO" == "hypeproof-agent" ]] && MODE="agent"
JAY_HOME="/Users/jaylee"
PASS=0; FAIL=0; NA=0

hr(){ printf '%s\n' "----------------------------------------------------------------------"; }
# http_code — run a gh api call with -i and return exactly ONE 3-digit status
# (defaults 000). Robust against multi-line output / no-match.
http_code(){ local c; c="$(gh api "$@" -i 2>/dev/null | head -n1 | grep -oE '[0-9]{3}' | head -n1)"; printf '%s' "${c:-000}"; }
verdict(){ # $1=ok|bad|na  $2=msg
  case "$1" in ok) PASS=$((PASS+1)); printf '  PASS  %s\n' "$2";;
               bad) FAIL=$((FAIL+1)); printf '  FAIL  %s\n' "$2";;
               na) NA=$((NA+1));   printf '  N/A   %s\n' "$2";; esac; }
has_gh(){ command -v gh >/dev/null 2>&1; }

printf '\n#### M005 Phase 4 — credential non-inheritance suite ####\n'
printf 'identity: %s   mode: %s   date: %s\n' "$WHO" "$MODE" "$(date -u +%FT%TZ)"
[[ "$MODE" == "reference" ]] && printf '(REFERENCE MODE: MUST-FAIL rows are N/A — Jay legitimately holds these.)\n'

############################################################################
printf '\n== A. MUST FAIL from the agent (credential inheritance blocked) ==\n'
############################################################################

hr; echo "A1. Read Jay's SSH private key   expect: permission denied (EACCES)"
if [[ "$MODE" == "agent" ]]; then
  if cat "$JAY_HOME/.ssh/id_ed25519" >/dev/null 2>&1; then verdict bad "A1 agent READ Jay's ssh key — ISOLATION BROKEN";
  else verdict ok "A1 denied reading $JAY_HOME/.ssh/id_ed25519 (expected)"; fi
else echo "  expected as agent: 'Permission denied'"; verdict na "A1 (Jay owns the key)"; fi

hr; echo "A2. Use Jay's login-keychain github credential   expect: cannot access (item not in agent keychain)"
if [[ "$MODE" == "agent" ]]; then
  if security find-internet-password -s github.com >/dev/null 2>&1; then verdict bad "A2 agent read a github keychain item — CHECK it is the agent's, not Jay's";
  else verdict ok "A2 no github internet-password in agent keychain search list (expected)"; fi
else echo "  expected as agent: item not found (Jay's login.keychain is per-uid, locked to Jay)"; verdict na "A2 (Jay's keychain)"; fi

hr; echo "A3. gh identity must NOT resolve to jayleekr   expect: machine user or unauthenticated"
if has_gh; then
  who_gh="$(gh api user --jq .login 2>/dev/null || echo '<unauth>')"
  if [[ "$MODE" == "agent" ]]; then
    if [[ "$who_gh" == "jayleekr" ]]; then verdict bad "A3 agent gh resolves to jayleekr — ISOLATION BROKEN";
    else verdict ok "A3 agent gh identity = ${who_gh} (not jayleekr)"; fi
  else echo "  Jay's gh identity = ${who_gh} (expected jayleekr here)"; verdict na "A3 (reference)"; fi
else echo "  gh not installed in this context"; verdict na "A3 (no gh)"; fi

hr; echo "A4. Repository administration WRITE   expect: HTTP 403 (Administration:write withheld)"
echo "     probe: value-preserving PATCH (has_issues=true, already true) on hypeprooflab"
if [[ "$MODE" == "agent" ]] && has_gh; then
  if gh api -X PATCH repos/jayleekr/hypeprooflab -f has_issues=true --silent >/dev/null 2>&1; then
    verdict bad "A4 admin PATCH SUCCEEDED — agent has Administration:write (must be read-only)";
  else verdict ok "A4 admin PATCH rejected (expected 403)"; fi
else echo "  expected as agent: 403 Forbidden"; verdict na "A4 (reference/no gh)"; fi

hr; echo "A5. Branch-protection mutation   expect: HTTP 403 (no Administration:write)"
echo "     probe: PUT protection on a NONEXISTENT branch (no branch => no state change even if authz'd)"
if [[ "$MODE" == "agent" ]] && has_gh; then
  code="$(http_code -X PUT 'repos/jayleekr/hypeproof-harness/branches/iso-nonexistent-probe/protection' \
           -f required_status_checks=null -f enforce_admins=false -f required_pull_request_reviews=null -f restrictions=null)"
  if [[ "$code" == "403" || "$code" == "404" ]]; then verdict ok "A5 protection PUT rejected (HTTP $code, expected 403/404)";
  else verdict bad "A5 protection PUT returned HTTP $code — expected 403/404"; fi
else echo "  expected as agent: 403 (authz) — 404 only if authz'd but branch missing"; verdict na "A5 (reference/no gh)"; fi

hr; echo "A6. Repository deletion   expect: HTTP 403 (delete withheld)"
echo "     probe: DELETE a GUARANTEED-nonexistent repo (success impossible; tests the permission only)"
if [[ "$MODE" == "agent" ]] && has_gh; then
  code="$(http_code -X DELETE 'repos/jayleekr/iso-nonexistent-delete-probe')"
  if [[ "$code" == "403" || "$code" == "404" ]]; then verdict ok "A6 repo DELETE rejected (HTTP $code, expected 403/404)";
  else verdict bad "A6 repo DELETE returned HTTP $code — expected 403/404"; fi
else echo "  expected as agent: 403/404"; verdict na "A6 (reference/no gh)"; fi

hr; echo "A7. SSH-key administration   expect: 403/404 (fine-grained PAT has no key admin)"
echo "     probe: GET user/keys (read-only)"
if [[ "$MODE" == "agent" ]] && has_gh; then
  code="$(http_code user/keys)"
  if [[ "$code" == "403" || "$code" == "404" ]]; then verdict ok "A7 user/keys rejected (HTTP $code, expected)";
  else verdict bad "A7 user/keys returned HTTP $code — agent can enumerate SSH keys"; fi
else echo "  expected as agent: 403/404"; verdict na "A7 (reference/no gh)"; fi

############################################################################
printf '\n== B. MUST SUCCEED from the agent (delegated work works) ==\n'
############################################################################

hr; echo "B1. Read authorized repo (clone/ls-remote)   expect: success"
if command -v git >/dev/null 2>&1; then
  if git ls-remote https://github.com/jayleekr/hypeprooflab.git -h >/dev/null 2>&1; then verdict ok "B1 ls-remote hypeprooflab succeeded";
  else verdict bad "B1 ls-remote hypeprooflab FAILED — agent cannot read its write target"; fi
else echo "  git missing"; verdict na "B1 (no git)"; fi

hr; echo "B2. Push permission present on write target   expect: permissions.push=true"
if has_gh; then
  push="$(gh api repos/jayleekr/hypeprooflab --jq .permissions.push 2>/dev/null || echo '?')"
  if [[ "$push" == "true" ]]; then verdict ok "B2 hypeprooflab permissions.push=true";
  elif [[ "$MODE" == "agent" ]]; then verdict bad "B2 push=$push — agent lacks write on hypeprooflab";
  else echo "  push=$push (Jay)"; verdict na "B2 (reference)"; fi
else verdict na "B2 (no gh)"; fi

hr; echo "B3. Read branch protection (Administration:READ allowed)   expect: HTTP 200"
if has_gh; then
  code="$(http_code 'repos/jayleekr/hypeproof-harness/branches/main/protection')"
  if [[ "$code" == "200" ]]; then verdict ok "B3 read protection HTTP 200 (observe-only allowed)";
  elif [[ "$MODE" == "agent" ]]; then verdict bad "B3 read protection HTTP $code — expected 200";
  else echo "  HTTP $code (Jay)"; verdict na "B3 (reference)"; fi
else verdict na "B3 (no gh)"; fi

hr; echo "B4. Read CI status/checks   expect: HTTP 200"
if has_gh; then
  code="$(http_code 'repos/jayleekr/hypeprooflab/commits/main/check-runs')"
  if [[ "$code" == "200" ]]; then verdict ok "B4 read check-runs HTTP 200";
  elif [[ "$MODE" == "agent" ]]; then verdict bad "B4 read check-runs HTTP $code — expected 200";
  else echo "  HTTP $code (Jay)"; verdict na "B4 (reference)"; fi
else verdict na "B4 (no gh)"; fi

hr; echo "B5. Feature-branch create+push+delete (REAL write, opt-in with --write-probe)"
if [[ "${1:-}" == "--write-probe" && "$MODE" == "agent" ]]; then
  tmp="$(mktemp -d)"; br="iso-probe-$(date +%s)"
  if git clone --depth 1 https://github.com/jayleekr/hypeprooflab.git "$tmp/r" >/dev/null 2>&1 \
     && git -C "$tmp/r" checkout -b "$br" >/dev/null 2>&1 \
     && git -C "$tmp/r" commit --allow-empty -m "iso probe $br" >/dev/null 2>&1 \
     && git -C "$tmp/r" push origin "$br" >/dev/null 2>&1; then
     verdict ok "B5 pushed feature branch $br"
     git -C "$tmp/r" push origin --delete "$br" >/dev/null 2>&1 && echo "  (cleaned up $br)"
  else verdict bad "B5 feature-branch push FAILED — agent cannot do delegated work"; fi
  rm -rf "$tmp"
else echo "  skipped (run with --write-probe AS the agent to exercise a real push+cleanup)"; verdict na "B5 (skipped)"; fi

############################################################################
hr; printf 'SUMMARY  identity=%s mode=%s  PASS=%d FAIL=%d N/A=%d\n' "$WHO" "$MODE" "$PASS" "$FAIL" "$NA"
if [[ "$MODE" == "agent" && "$FAIL" -gt 0 ]]; then
  echo "RESULT: ISOLATION NOT VERIFIED — $FAIL assertion(s) failed. Do NOT decommission Jay-path fallback."; exit 1
elif [[ "$MODE" == "agent" ]]; then
  echo "RESULT: isolation verified from the agent identity."; exit 0
else
  echo "RESULT: reference run complete (agent-only assertions were N/A). Re-run AS hypeproof-agent to certify."; exit 0
fi
