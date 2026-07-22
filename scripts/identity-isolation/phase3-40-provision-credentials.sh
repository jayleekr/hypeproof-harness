#!/usr/bin/env bash
# phase3-40-provision-credentials.sh — EMIT the credential-provisioning plan for
# the agent account. Executes NOTHING and PRINTS NO SECRET VALUES (only names,
# paths, scopes). Actual token minting is HUMAN-ONLY (Phase 2 / GitHub UI).
#
# Two credentials the autonomous runtime needs, both provisioned INSIDE the
# agent account so nothing is inherited from Jay:
#   (1) GitHub fine-grained PAT (machine user $II_GH_LOGIN) — for git over HTTPS.
#   (2) Claude Code OAuth token — for the `claude` CLI the cron jobs invoke.
#
# The PAT is a STATIC secret. That is deliberate and is the deciding factor for
# Phase 2 (see docs/M005-IDENTITY-ISOLATION.ko.md "Phase 2 decision"): the
# existing launchd model already reads a static token from a 0600 env file, so a
# static PAT drops in with zero new moving parts. A GitHub App would require a
# per-run JWT->installation-token mint step (1h expiry) AND still keeps a static
# app private key at rest — more code, same at-rest exposure.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; source "$HERE/lib.sh"
: "${II_HELP:=0}"; ii_parse_args "$@"
[[ "$II_HELP" == "1" ]] && { grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

c_head "Phase 3 · Step 40 — provision agent credentials (HUMAN-ONLY, no values printed)"

c_head "(1) GitHub fine-grained PAT — machine user $II_GH_LOGIN"
c_info "Create/rotate is done in the GitHub UI by the human (Phase 2). This tool never issues tokens."
c_info "Required grants (from policy/automation-identity.yaml — validate against it):"
c_info "   Metadata:read  Contents:write  Pull requests:write  Issues:write"
c_info "   Administration:READ-only  Actions:read  Checks:read"
c_info "Explicitly WITHHELD: Administration:write, Secrets, Environments, Workflows, Actions:write(default)."
c_info "Resource owner: $II_GH_LOGIN.  Repos: hypeprooflab (write); harness/studio/sediment (read)."
plan_comment "Store the PAT in the AGENT's own git credential store (owner-only), NOT Jay's keychain:"
plan "sudo -u $II_AGENT_USER git config --file $II_AGENT_HOME/.gitconfig credential.helper 'store --file=$II_AGENT_HOME/.config/git/credentials'"
plan "sudo -u $II_AGENT_USER mkdir -p $II_AGENT_HOME/.config/git && sudo -u $II_AGENT_USER chmod 700 $II_AGENT_HOME/.config/git"
plan_comment "Then, IN AN INTERACTIVE agent shell (su - $II_AGENT_USER), a single authenticated"
plan_comment "git push will prompt once and the store captures it 0600. Do NOT echo the token."
plan "sudo -u $II_AGENT_USER chmod 600 $II_AGENT_HOME/.config/git/credentials   # after first auth"
plan_comment "ALTERNATIVE (no on-disk token): 'gh auth login' as the agent using the PAT via stdin,"
plan_comment "storing it in the AGENT's gh keyring — still isolated from Jay's keyring by uid."

c_head "(2) Claude Code OAuth token — agent's own env file"
c_info "The cron jobs source ~/.config/cron/env for CLAUDE_CODE_OAUTH_TOKEN (bare KEY=value, set -a)."
c_info "The agent needs its OWN, provisioned by the human. This tool prints no value."
plan "sudo -u $II_AGENT_USER touch $II_AGENT_HOME/.config/cron/env"
plan "sudo -u $II_AGENT_USER chmod 600 $II_AGENT_HOME/.config/cron/env"
plan_comment "Human then edits $II_AGENT_HOME/.config/cron/env and adds (value from the agent's"
plan_comment "own Claude Code login, NOT Jay's):   CLAUDE_CODE_OAUTH_TOKEN=..."
plan_comment "Never copy Jay's $II_HUMAN_HOME/.config/cron/env into the agent home."

c_head "Isolation asserts (verified for real in Phase 4)"
c_info "Agent PAT store:   $II_AGENT_HOME/.config/git/credentials   owner $II_AGENT_USER 0600"
c_info "Agent Claude env:  $II_AGENT_HOME/.config/cron/env          owner $II_AGENT_USER 0600"
c_info "Agent must have NO gh auth to Jay's account and NO readable path to Jay's ssh key / keychain."
c_info ""
c_info "Rollback: revoke the PAT in GitHub UI; 'rm' the agent cred files (removed with account anyway)."
ii_emit_flush
