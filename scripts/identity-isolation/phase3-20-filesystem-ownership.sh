#!/usr/bin/env bash
# phase3-20-filesystem-ownership.sh — EMIT the ownership/permission plan that
# makes Jay's credential stores unreadable to the agent uid, and defines what
# the agent owns. Executes NOTHING. Prints perms only, never file contents.
#
# Two halves:
#   A) HARDEN Jay's stores so a different uid (the agent) cannot read them.
#      After the uid split, macOS already denies cross-uid reads of 0600 files
#      and of the per-user login keychain; this step closes the group/world
#      readable gaps the preflight found (e.g. a 0644 ~/.gitconfig).
#   B) DEFINE the agent-owned tree (home, runtime checkouts, its own creds).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; source "$HERE/lib.sh"
: "${II_HELP:=0}"; ii_parse_args "$@"
[[ "$II_HELP" == "1" ]] && { grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

c_head "Phase 3 · Step 20 — filesystem ownership & isolation"

c_head "A) Harden Jay's credential stores (run as jaylee; no sudo needed)"
plan_comment "Directories -> 0700 so another uid cannot even list them."
plan "chmod 700 $II_HUMAN_HOME/.ssh"
plan "chmod 700 $II_HUMAN_HOME/.config $II_HUMAN_HOME/.config/gh $II_HUMAN_HOME/.config/cron 2>/dev/null || true"
plan_comment "Private key + token files -> 0600 (owner-only)."
plan "chmod 600 $II_HUMAN_HOME/.ssh/id_ed25519"
plan "chmod 600 $II_HUMAN_HOME/.config/cron/env"
plan "chmod 600 $II_HUMAN_HOME/.config/gh/hosts.yml 2>/dev/null || true"
plan_comment "~/.gitconfig is 0644 today (world-readable) -> tighten to 0600 so the"
plan_comment "agent cannot read Jay's credential-helper / user config."
plan "chmod 600 $II_HUMAN_HOME/.gitconfig"
plan_comment "macOS login keychain (~/Library/Keychains/*.keychain-db) is already"
plan_comment "per-uid + locked; a different uid CANNOT use it. No action, verified in Phase 4."

c_head "B) Agent-owned tree (HUMAN-ONLY: sudo, ownership set to $II_AGENT_USER)"
plan "sudo chown $II_AGENT_USER:staff $II_AGENT_HOME && sudo chmod 700 $II_AGENT_HOME"
plan "sudo -u $II_AGENT_USER mkdir -p $II_AGENT_RUNTIME"
plan "sudo -u $II_AGENT_USER mkdir -p $II_AGENT_HOME/.config/cron"
plan "sudo -u $II_AGENT_USER mkdir -p $II_AGENT_HOME/.config/gh"
plan "sudo -u $II_AGENT_USER mkdir -p $II_AGENT_HOME/Library/LaunchAgents"
plan "sudo -u $II_AGENT_USER chmod 700 $II_AGENT_HOME/.config $II_AGENT_HOME/.config/cron $II_AGENT_HOME/.config/gh"
plan_comment "The agent MUST NOT own or symlink into Jay's home. Verify no cross-links:"
plan "sudo find $II_AGENT_HOME -maxdepth 3 -type l -lname '$II_HUMAN_HOME/*' -print   # expect: no output"

c_head "Ownership map (target end state)"
c_info "$II_HUMAN_HOME/.ssh/**            owner jaylee            0700 dir / 0600 keys  (agent: DENIED)"
c_info "$II_HUMAN_HOME/.config/cron/env   owner jaylee            0600                  (agent: DENIED)"
c_info "$II_HUMAN_HOME/.config/gh/**      owner jaylee            0700/0600             (agent: DENIED)"
c_info "$II_HUMAN_HOME/Library/Keychains  owner jaylee (per-uid)  macOS-enforced        (agent: DENIED)"
c_info "$II_AGENT_HOME                    owner $II_AGENT_USER    0700                  (jaylee: not needed)"
c_info "$II_AGENT_RUNTIME/**              owner $II_AGENT_USER    0700                  (repo checkouts)"
c_info "$II_AGENT_HOME/.config/cron/env   owner $II_AGENT_USER    0600                  (agent Claude token)"
c_info ""
c_info "Rollback: phase3-90-rollback.sh (step 20 section) restores Jay perms; agent tree removed with the account."
ii_emit_flush
