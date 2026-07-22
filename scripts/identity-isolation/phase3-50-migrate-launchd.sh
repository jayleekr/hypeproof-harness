#!/usr/bin/env bash
# phase3-50-migrate-launchd.sh — migrate the com.hypeproof.cron.* autonomous
# jobs from Jay's LaunchAgent domain to the agent's context.
#
# It GENERATES transformed plist files into an output dir (safe: writes only
# inside the repo/output dir). It does NOT install them and does NOT run
# launchctl — those lines are EMITTED for the human.
#
#   default (--dry-run):  transform live plists -> ./generated/launchd/, print install plan
#   --emit <file>:        also write the install/bootout commands to <file>
#   --out <dir>:          output dir for generated plists (default: <script>/generated/launchd)
#
# WHY LaunchDaemon, not LaunchAgent (macOS constraint, HIGH confidence):
#   A user LaunchAgent only runs inside that user's *GUI (aqua) login session*.
#   A hidden, non-interactive service account is never "logged in", so its
#   LaunchAgents would not fire reliably. A LaunchDaemon in /Library/LaunchDaemons
#   with <UserName>hypeproof-agent</UserName> runs at boot regardless of login,
#   AS that user (privilege drop). That is the robust target for a headless agent.
#   (Alternative kept in the docs: keep LaunchAgents + `launchctl bootstrap
#    gui/<agent-uid>` while the account is loaded — fragile; not recommended.)
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; source "$HERE/lib.sh"
OUT="$HERE/generated/launchd"
: "${II_HELP:=0}"
# lightweight extra-arg parse for --out (before the shared parser)
args=(); while [[ $# -gt 0 ]]; do case "$1" in --out) shift; OUT="$1";; *) args+=("$1");; esac; shift; done
ii_parse_args ${args[@]+"${args[@]}"}
[[ "$II_HELP" == "1" ]] && { grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

SRC="$II_HUMAN_HOME/Library/LaunchAgents"
DAEMON_DIR="/Library/LaunchDaemons"           # install target (human, sudo)
mkdir -p "$OUT"

c_head "Phase 3 · Step 50 — migrate com.hypeproof.cron.* to agent LaunchDaemons"
c_info "source plists : $SRC/com.hypeproof.cron.*.plist"
c_info "generated into: $OUT   (review these; NOT yet installed)"
c_info "install target: $DAEMON_DIR (human + sudo)"

shopt -s nullglob
count=0
for src in "$SRC"/com.hypeproof.cron.*.plist; do
  base="$(basename "$src" .plist)"
  # new label: distinguish the daemon from Jay's agent job, and re-scope paths.
  new_label="${base/com.hypeproof.cron./com.hypeproof.agent.cron.}"
  dst="$OUT/${new_label}.plist"
  # Transform: rehome paths jaylee->agent, add UserName/GroupName, add
  # EnvironmentVariables HOME override, keep schedule. Uses only string subs so
  # the schedule / program args structure is preserved verbatim.
  # Order matters: the specific workspace remap runs first, then a blanket
  # home-prefix rewrite catches every remaining /Users/jaylee/... path (e.g.
  # .npm-global/bin) so NOTHING resolves back into Jay's home. Any genuinely
  # shared resource must be re-provisioned in the agent home, not inherited.
  sed -E \
    -e "s#$II_HUMAN_HOME/CodeWorkspace/hypeprooflab#$II_AGENT_RUNTIME/hypeprooflab#g" \
    -e "s#>com\.hypeproof\.cron\.#>com.hypeproof.agent.cron.#g" \
    -e "s#<string>$II_HUMAN_HOME</string>#<string>$II_AGENT_HOME</string>#g" \
    -e "s#$II_HUMAN_HOME/#$II_AGENT_HOME/#g" \
    "$src" > "$dst.tmp"
  # inject <key>UserName</key><string>agent</string> + GroupName after <dict> open,
  # so the daemon drops privilege to the agent uid.
  awk -v u="$II_AGENT_USER" '
    /<dict>/ && !done { print; print "  <key>UserName</key>"; print "  <string>" u "</string>";
                        print "  <key>GroupName</key>"; print "  <string>staff</string>"; done=1; next }
    { print }' "$dst.tmp" > "$dst"
  rm -f "$dst.tmp"
  count=$((count+1))
  printf '  generated  %s\n' "${dst##*/}"
done
shopt -u nullglob

if [[ "$count" == "0" ]]; then
  c_warn "no source com.hypeproof.cron.* plists found under $SRC (run as jaylee, or point --out)."
fi
c_ok "generated $count LaunchDaemon plist(s) into $OUT"

c_head "Install plan (HUMAN-ONLY — sudo)"
plan_comment "1) Stop the OLD Jay-domain agent jobs so they don't double-run."
plan "for p in $SRC/com.hypeproof.cron.*.plist; do launchctl bootout gui/501/\$(basename \"\$p\" .plist) 2>/dev/null || true; done"
plan_comment "2) Install the new daemons (root-owned, 0644) and load them in the system domain."
plan "sudo cp $OUT/com.hypeproof.agent.cron.*.plist $DAEMON_DIR/"
plan "sudo chown root:wheel $DAEMON_DIR/com.hypeproof.agent.cron.*.plist"
plan "sudo chmod 644 $DAEMON_DIR/com.hypeproof.agent.cron.*.plist"
plan "for p in $DAEMON_DIR/com.hypeproof.agent.cron.*.plist; do sudo launchctl bootstrap system \"\$p\"; done"
plan_comment "3) Verify each is loaded and will run as the agent uid, not Jay."
plan "sudo launchctl print system/com.hypeproof.agent.cron.issue-solver | grep -E 'username|state|program'"

c_head "Old Jay-domain plists — disable (do NOT delete until Phase 4 passes)"
plan_comment "Move aside so rollback is trivial (rename, don't rm)."
plan "mkdir -p $SRC/.migrated-to-agent && mv $SRC/com.hypeproof.cron.*.plist $SRC/.migrated-to-agent/"

c_info ""
c_info "Rollback: phase3-90-rollback.sh (step 50) — bootout daemons, restore Jay plists from .migrated-to-agent."
ii_emit_flush
