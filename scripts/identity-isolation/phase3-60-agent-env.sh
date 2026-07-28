#!/usr/bin/env bash
# phase3-60-agent-env.sh — EMIT the minimal environment for the agent runtime.
# Executes NOTHING; prints no secret values.
#
# The existing cron-prompts/cron-env.sh is already HOME-relative (it sources
# $HOME/.config/cron/env and derives the workspace from its own path), so the
# agent's own checkout copy works under the agent uid without edits. This step
# only pins the few values that must point at the agent, not Jay.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; source "$HERE/lib.sh"
: "${II_HELP:=0}"; ii_parse_args "$@"
[[ "$II_HELP" == "1" ]] && { grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

c_head "Phase 3 · Step 60 — minimal agent environment"
c_info "Runtime workspace (Step 30 checkout):  HYPEPROOF_WORKSPACE=$II_AGENT_RUNTIME/hypeprooflab"
c_info "Claude token file (Step 40):           $II_AGENT_HOME/.config/cron/env  (CLAUDE_CODE_OAUTH_TOKEN=...)"
c_info "Git PAT store (Step 40):               $II_AGENT_HOME/.config/git/credentials"
c_info "HOME for every job:                    $II_AGENT_HOME  (set via LaunchDaemon EnvironmentVariables)"
c_info "PATH (agent-scoped, no Jay paths):     $II_AGENT_HOME/.local/bin:/opt/homebrew/bin:/usr/bin:/bin"

c_head "Assertions the agent env MUST satisfy (checked in Phase 4)"
c_info "- No GH_TOKEN / GITHUB_TOKEN pointing at Jay's OAuth token."
c_info "- No SSH_AUTH_SOCK / ssh-agent forwarding Jay's key into the agent session."
c_info "- HOME never resolves to $II_HUMAN_HOME for any agent job."
plan_comment "Confirm agent's own cron-env sources the AGENT file (home-relative, no edit needed):"
plan "sudo -u $II_AGENT_USER grep -n 'HOME/.config/cron/env' $II_AGENT_RUNTIME/hypeprooflab/cron-prompts/cron-env.sh"
plan_comment "Ensure no stray Jay token leaks into the agent env file:"
plan "sudo -u $II_AGENT_USER sh -c 'grep -l gho_ $II_AGENT_HOME/.config/cron/env 2>/dev/null && echo FINDING:owner-token-in-agent-env || echo ok'"
c_info ""
c_info "Rollback: agent env removed with the account (phase3-90 step 10)."
ii_emit_flush
