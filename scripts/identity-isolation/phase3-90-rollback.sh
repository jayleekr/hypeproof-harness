#!/usr/bin/env bash
# phase3-90-rollback.sh — EMIT the reverse of every Phase 3 step, in reverse
# order (50 -> 10). Executes NOTHING. Use this to back out a partial or full
# migration and return to the pre-M005 state (automation as jaylee).
#
# Rollback is ordered so the runtime is never left half-pointed: stop the new
# daemons first, restore Jay's jobs, THEN unwind ownership and the account.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; source "$HERE/lib.sh"
: "${II_HELP:=0}"; ii_parse_args "$@"
[[ "$II_HELP" == "1" ]] && { grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0; }
SRC="$II_HUMAN_HOME/Library/LaunchAgents"
DAEMON_DIR="/Library/LaunchDaemons"

c_head "Phase 3 · Rollback (reverse order) — HUMAN-ONLY, sudo"

c_head "Undo Step 50 — launchd: stop agent daemons, restore Jay's jobs"
plan "for p in $DAEMON_DIR/com.hypeproof.agent.cron.*.plist; do sudo launchctl bootout system \"\$p\" 2>/dev/null || true; done"
plan "sudo rm -f $DAEMON_DIR/com.hypeproof.agent.cron.*.plist"
plan "[ -d $SRC/.migrated-to-agent ] && mv $SRC/.migrated-to-agent/com.hypeproof.cron.*.plist $SRC/ || true"
plan "for p in $SRC/com.hypeproof.cron.*.plist; do launchctl bootstrap gui/501 \"\$p\" 2>/dev/null || true; done"

c_head "Undo Steps 60/40/30 — agent runtime + credentials"
plan_comment "Revoke the machine-user PAT in the GitHub UI (human). Then drop on-disk copies:"
plan "sudo rm -rf $II_AGENT_RUNTIME"
plan "sudo rm -f  $II_AGENT_HOME/.config/git/credentials $II_AGENT_HOME/.config/cron/env"

c_head "Undo Step 20 — restore Jay's credential-store perms to pre-M005"
plan_comment "Only if you tightened them AND something depended on the looser mode:"
plan "chmod 644 $II_HUMAN_HOME/.gitconfig    # original mode was 0644"
plan_comment "(.ssh 0700 / keys 0600 / cron env 0600 were already correct — leave them.)"

c_head "Undo Step 10 — remove the agent account (LAST, only for full rollback)"
plan "sudo sysadminctl -deleteUser $II_AGENT_USER -secure"
plan "sudo defaults delete /Library/Preferences/com.apple.loginwindow HiddenUsersList 2>/dev/null || true"
plan_comment "Verify the account and home are gone:"
plan "id $II_AGENT_USER 2>&1 | grep -q 'no such user' && echo 'ok: account removed'"
plan "[ ! -d $II_AGENT_HOME ] && echo 'ok: agent home removed'"

c_head "Post-rollback verification"
plan "launchctl print gui/501/com.hypeproof.cron.issue-solver >/dev/null 2>&1 && echo 'ok: Jay job back' || echo 'CHECK: Jay job not loaded'"
c_info "State after full rollback == pre-M005: automation runs as jaylee again (accepting the original risk)."
ii_emit_flush
