#!/usr/bin/env bash
# phase3-10-create-account.sh — EMIT the human-run commands that create the
# dedicated `hypeproof-agent` macOS account. Executes NOTHING privileged.
#
#   default (--dry-run): print the plan + the exact sudo commands
#   --emit <file>      : write the commands to <file> (0700) for the human
#   --apply            : REFUSED (privileged; human-only)
#
# Design intent of the account:
#   - Standard (NON-admin) user. MUST NOT be in the `admin` group -> cannot sudo.
#   - Own home /Users/hypeproof-agent, separate from Jay's.
#   - Hidden from the login window (service account, not an interactive login).
#   - No inherited access to Jay's keychain / ssh / gh (that is Phase 3 steps
#     20 + 40; this step only creates the empty, isolated identity).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; source "$HERE/lib.sh"
: "${II_HELP:=0}"; ii_parse_args "$@"
[[ "$II_HELP" == "1" ]] && { grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

c_head "Phase 3 · Step 10 — create the isolated agent account ($II_AGENT_USER)"
c_warn "HUMAN-ONLY: every line below needs sudo. This tool does not run them."

if id "$II_AGENT_USER" >/dev/null 2>&1; then
  c_bad "$II_AGENT_USER already exists — SKIP creation. Verify it is non-admin:"
  plan "dscl . -read /Groups/admin GroupMembership | tr ' ' '\\n' | grep -qx $II_AGENT_USER && echo 'FINDING: agent is admin — remove it' || echo 'ok: not admin'"
  ii_emit_flush; exit 0
fi

plan_comment "1) Create a STANDARD (non-admin) service account with its own home + zsh."
plan_comment "   sysadminctl auto-assigns the next free UID (do not hardcode one)."
plan "sudo sysadminctl -addUser $II_AGENT_USER \\"
plan "     -fullName \"HypeProof Autonomous Agent\" \\"
plan "     -home $II_AGENT_HOME \\"
plan "     -shell /bin/zsh"
plan_comment "   (You will be prompted for the new account password interactively;"
plan_comment "    choose a strong one and store it in JAY's password manager, NOT on disk.)"

plan_comment "2) Assert it is NOT an admin (must print nothing / non-member)."
plan "dscl . -read /Groups/admin GroupMembership | tr ' ' '\\n' | grep -x $II_AGENT_USER \\"
plan "  && { echo 'FINDING: agent is admin — removing'; sudo dscl . -delete /Groups/admin GroupMembership $II_AGENT_USER; } \\"
plan "  || echo 'ok: $II_AGENT_USER is not in admin group'"

plan_comment "3) Hide the account from the login window (service account, non-interactive)."
plan "sudo dscl . -create /Users/$II_AGENT_USER IsHidden 1"
plan "sudo defaults write /Library/Preferences/com.apple.loginwindow HiddenUsersList -array-add $II_AGENT_USER"

plan_comment "4) Confirm the home directory exists and is owned by the agent, mode 0700."
plan "sudo mkdir -p $II_AGENT_HOME"
plan "sudo chown $II_AGENT_USER:staff $II_AGENT_HOME"
plan "sudo chmod 700 $II_AGENT_HOME    # <- 700 so Jay's other processes can't read agent home either"

plan_comment "5) Verify (expected: uid printed, gid=20/staff, groups WITHOUT 'admin')."
plan "id $II_AGENT_USER"
plan "groups $II_AGENT_USER"

c_info ""
c_info "Expected result: '$II_AGENT_USER' exists, non-admin, hidden, owns $II_AGENT_HOME (0700)."
c_info "Rollback for this step: scripts/identity-isolation/phase3-90-rollback.sh (step 10 section)."
ii_emit_flush
