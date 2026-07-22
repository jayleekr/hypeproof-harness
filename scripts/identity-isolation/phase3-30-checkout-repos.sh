#!/usr/bin/env bash
# phase3-30-checkout-repos.sh — EMIT the plan to clone the runtime repos into
# the agent's home over HTTPS (so the fine-grained PAT is used, NOT an SSH deploy
# key — see finding A7 in policy/automation-identity.yaml). Executes NOTHING.
#
# Why fresh clones in the agent home instead of reusing Jay's checkouts:
#   Jay's checkouts under $II_HUMAN_HOME/CodeWorkspace have ssh remotes and sit
#   in Jay's home (agent uid can't read them once home is 0700). The agent gets
#   its own working copies under $II_AGENT_RUNTIME with https remotes bound to
#   the machine-user PAT via a git credential store the agent owns.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; source "$HERE/lib.sh"
: "${II_HELP:=0}"; ii_parse_args "$@"
[[ "$II_HELP" == "1" ]] && { grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

c_head "Phase 3 · Step 30 — clone runtime repos into the agent home (HTTPS only)"
c_warn "HUMAN-ONLY: run each 'sudo -u $II_AGENT_USER ...' line from an admin shell."
plan_comment "Prereq: Step 40 (credentials) provisions the PAT store the clones authenticate against."
plan_comment "All remotes are HTTPS on purpose (A7): the PAT's withheld Workflows scope only"
plan_comment "bites on the HTTPS transport; an SSH deploy key would bypass it."

for repo in "${II_AGENT_REPOS[@]}"; do
  name="${repo##*/}"
  plan "sudo -u $II_AGENT_USER git -C $II_AGENT_RUNTIME clone https://github.com/${repo}.git $name"
done

plan_comment "Pin every remote to HTTPS (defensive — reject any ssh remote sneaking in)."
plan "for d in $II_AGENT_RUNTIME/*/; do \\"
plan "  url=\$(sudo -u $II_AGENT_USER git -C \"\$d\" remote get-url origin); \\"
plan "  case \"\$url\" in git@*|ssh://*) echo \"FINDING: ssh remote in \$d — fix to https\";; esac; \\"
plan "done"

plan_comment "Point the autonomous runtime at the agent checkouts (env, set in Step 60)."
plan_comment "e.g. HYPEPROOF_WORKSPACE=$II_AGENT_RUNTIME/hypeprooflab"

c_head "Checkout map (target)"
for repo in "${II_AGENT_REPOS[@]}"; do
  name="${repo##*/}"
  role="read"; [[ "$name" == "hypeprooflab" ]] && role="WRITE (feature branches + PRs only)"
  printf '  %-42s <- https://github.com/%s  [%s]\n' "$II_AGENT_RUNTIME/$name" "$repo" "$role"
done
c_info ""
c_info "Rollback: removed with the account (phase3-90 step 10) or 'rm -rf $II_AGENT_RUNTIME/*'."
ii_emit_flush
