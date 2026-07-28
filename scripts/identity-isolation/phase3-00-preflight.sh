#!/usr/bin/env bash
# phase3-00-preflight.sh — READ-ONLY assessment of the pre-migration state.
#
# This is the ONLY Phase 3 script that touches nothing and is safe to run now,
# as jaylee, before any human-gated change. It reports the facts every later
# step depends on, and flags drift from the M005 Phase 0 measured baseline.
# It NEVER prints a secret value (scopes / paths / perms only).
#
# Exit 0 = state matches expectations; exit 1 = drift the human should resolve.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; source "$HERE/lib.sh"
[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && { grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

fail=0

c_head "1. Current OS identity (expected: $II_HUMAN_USER / uid 501)"
c_info "whoami            = $(whoami)"
c_info "uid               = $(id -u)  gid = $(id -g)"
[[ "$(id -u)" == "501" ]] || { c_warn "not running as uid 501 — read the results in context"; }

c_head "2. Agent account must NOT exist yet (expected: absent)"
if id "$II_AGENT_USER" >/dev/null 2>&1; then
  c_bad "$II_AGENT_USER already exists (uid $(id -u "$II_AGENT_USER")) — Phase 3 create step is a no-op / already run"
else
  c_ok "$II_AGENT_USER absent — ready to be created by the human create step"
fi

c_head "3. GitHub identity in use (expected: jayleekr, over-scoped OAuth)"
if command -v gh >/dev/null 2>&1; then
  # gh redacts the token itself; we only surface login + scopes.
  gh auth status 2>&1 | sed -E 's/(gh[pousr]_[A-Za-z0-9]+)/[REDACTED]/g' | sed 's/^/  /'
  local_login="$(gh api user --jq .login 2>/dev/null || echo '?')"
  c_info "resolved login    = ${local_login}"
  [[ "$local_login" == "jayleekr" ]] && c_warn "automation still borrows Jay's identity (the thing M005 removes)"
else
  c_warn "gh not on PATH in this context"
fi

c_head "4. Git transports per repo (expected: harness/studio/sediment=ssh, hypeprooflab=https)"
for r in hypeproof-harness hypeprooflab hypeproof-studio sediment; do
  d="$II_HUMAN_HOME/CodeWorkspace/$r"
  if [[ -e "$d/.git" ]]; then
    url="$(git -C "$d" remote get-url origin 2>/dev/null | sed -E 's#//[^@]*@#//[REDACTED]@#')"
    printf '  %-18s %s\n' "$r" "$url"
  else
    printf '  %-18s (no checkout here)\n' "$r"
  fi
done

c_head "5. Owner credential stores — perms only, NO contents (Jay-owned, must stay Jay-only)"
for f in "$II_HUMAN_HOME/.ssh/id_ed25519" "$II_HUMAN_HOME/.config/cron/env" \
         "$II_HUMAN_HOME/.gitconfig" "$II_HUMAN_HOME/.config/gh/hosts.yml"; do
  if [[ -e "$f" ]]; then
    stat -f '  %Sp %Su:%Sg  %N' "$f"
    # world-readable private material is a finding
    perms="$(stat -f '%Sp' "$f")"
    case "$f" in
      *id_ed25519|*cron/env|*hosts.yml)
        [[ "$perms" == *"r--r--"* || "$perms" == *"rw-r--"* ]] && { c_warn "$f is group/world-readable — agent account could read it after uid split unless tightened"; fail=1; } ;;
    esac
  else
    c_info "MISSING (ok if not applicable): $f"
  fi
done

c_head "6. launchd autonomous-runtime jobs (expected: com.hypeproof.cron.* under Jay)"
la="$II_HUMAN_HOME/Library/LaunchAgents"
n=$(ls "$la" 2>/dev/null | grep -cE '^com\.hypeproof\.cron\..*\.plist$' || true)
c_info "com.hypeproof.cron.*.plist jobs found: $n (backups excluded; these move to the agent domain in Phase 3 step 50)"
ls "$la" 2>/dev/null | grep -E '^com\.hypeproof\.cron\..*\.plist$' | sed 's/^/    /' | head -40

c_head "7. Free UID range (agent account will take the next free one; sysadminctl auto-picks)"
dscl . -list /Users UniqueID 2>/dev/null | awk '{print $2}' | sort -n | tail -3 | sed 's/^/  highest in use: /'

c_head "RESULT"
if [[ "$fail" == "0" ]]; then c_ok "preflight clean — proceed to the human-gated Phase 3 steps in order";
else c_warn "preflight noted items above (exit 1) — resolve or acknowledge before proceeding"; fi
exit "$fail"
