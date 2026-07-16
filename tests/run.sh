#!/usr/bin/env bash
# tests/run.sh — execute T-V1..T-V14 (T-V10 partial) against each consumer
#                plus harness-side checks (T-V5..T-V7, T-V12, T-V13, T-V14).
# Outputs a markdown table to stdout and writes tests/last-report.json.
#
# Exit code:
#   0  ⇔  FAIL=0 AND every consumer found AND every required PASS recorded
#   1  otherwise (FAIL, SKIP, or missing required PASS)
#
# Env overrides:
#   CONSUMER_<basename>=/abs/path    per-machine override for a consumer
#   T_V10_BASE_<basename>=<ref>      base ref for T-V10 atomic-PR scope check
#                                    (e.g. origin/main@pre-migration sha)
#
set -uo pipefail

HARNESS_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HARNESS_ROOT"

# Workspace base — mirrors scripts/sync.sh. Defaults to the parent of the
# MAIN checkout (resolved via git rev-parse --git-common-dir), so running
# from a linked worktree still finds sibling consumer clones.
if [ -z "${HYPEPROOF_WORKSPACE:-}" ]; then
  _common_dir="$(git -C "$HARNESS_ROOT" rev-parse --git-common-dir 2>/dev/null || true)"
  if [ -n "$_common_dir" ]; then
    case "$_common_dir" in
      /*) ;;
      *)  _common_dir="$HARNESS_ROOT/$_common_dir" ;;
    esac
    HYPEPROOF_WORKSPACE="$(cd "$_common_dir/../.." && pwd)"
  else
    HYPEPROOF_WORKSPACE="$(cd "$HARNESS_ROOT/.." && pwd)"
  fi
  unset _common_dir
fi

# ----- consumer resolution (mirrors sync.sh) -----
expand_path() {
  local p="$1"
  case "$p" in *[\'\"\`\;\|\&]*) echo "$p"; return ;; esac
  eval "echo $p"
}
_sanitize() { echo "$1" | tr '-' '_'; }
get_env_override() { local v="CONSUMER_$(_sanitize "$1")"; echo "${!v:-}"; }
get_t_v10_base()   { local v="T_V10_BASE_$(_sanitize "$1")"; echo "${!v:-}"; }

# Per-machine override: tests/consumers.local.txt (gitignored) wins over
# tests/consumers.txt if present (mirrors sync.sh).
CONSUMERS_FILE="tests/consumers.txt"
if [ -f "tests/consumers.local.txt" ]; then
  CONSUMERS_FILE="tests/consumers.local.txt"
  echo "Using local consumer list: $CONSUMERS_FILE" >&2
fi

CONSUMERS=()
while IFS= read -r raw; do
  raw="${raw%%#*}"; raw="${raw#"${raw%%[![:space:]]*}"}"; raw="${raw%"${raw##*[![:space:]]}"}"
  [ -z "$raw" ] && continue
  e="$(expand_path "$raw")"
  bn="$(basename "$e")"
  o="$(get_env_override "$bn")"
  [ -n "$o" ] && e="$o"
  CONSUMERS+=("$e")
done < "$CONSUMERS_FILE"

RESULTS=()   # "consumer|tid|status|note"
PASS=0; FAIL=0; DEFER=0; SKIP=0; NA=0
HARNESS_SHA="$(git rev-parse HEAD)"

mark() {
  RESULTS+=("$1|$2|$3|$4")
  case "$3" in
    PASS)  PASS=$((PASS+1)) ;;
    FAIL)  FAIL=$((FAIL+1)) ;;
    DEFER) DEFER=$((DEFER+1)) ;;
    SKIP)  SKIP=$((SKIP+1)) ;;
    N/A)   NA=$((NA+1)) ;;
  esac
}

SKILL_SRC="$HARNESS_ROOT/skills/skill-creator"
# Doc-fidelity list is DERIVED from scripts/sync.sh's DOCS=() so the gate and the
# vendoring source can never diverge (#47). sync.sh is the single source of truth
# for which docs are vendored to consumer/docs/<file>; add a doc there and this
# gate covers it automatically.
_sync_docs_line="$(grep -E '^DOCS=\(' "$HARNESS_ROOT/scripts/sync.sh" | head -1)"
_sync_docs_inner="${_sync_docs_line#*(}"
_sync_docs_inner="${_sync_docs_inner%%)*}"
# shellcheck disable=SC2206
DOCS=($_sync_docs_inner)
unset _sync_docs_line _sync_docs_inner
if [ "${#DOCS[@]}" -eq 0 ]; then
  echo "FATAL: could not derive DOCS from scripts/sync.sh (expected a 'DOCS=(...)' line)" >&2
  exit 2
fi
ROOT_AGENT_FILES=(CLAUDE.md AGENTS.md OPENCLAW.md)
N_CONSUMERS_FOUND=0

# ============================================================
# Per-consumer tests
# ============================================================
for C in "${CONSUMERS[@]}"; do
  CN="$(basename "$C")"

  # ---- CR-2: existence guard, counted as SKIP=fail (not silent) ----
  if [ ! -d "$C" ]; then
    mark "$CN" T-V1  SKIP "path absent: $C"
    mark "$CN" T-V2  SKIP "path absent"
    mark "$CN" T-V3  SKIP "path absent"
    mark "$CN" T-V4  SKIP "path absent"
    mark "$CN" T-V8  SKIP "path absent"
    mark "$CN" T-V9  SKIP "path absent"
    mark "$CN" T-V10 SKIP "path absent"
    mark "$CN" T-V11 SKIP "path absent"
    continue
  fi
  N_CONSUMERS_FOUND=$((N_CONSUMERS_FOUND+1))

  CONSUMER_SKILL="$C/.claude/skills/skill-creator"

  # ---- T-V1 content fidelity (BIDIRECTIONAL — CR-6) ----
  miss=0; extra=0
  while IFS= read -r -d '' f; do
    rel="${f#$SKILL_SRC/}"
    b="$CONSUMER_SKILL/$rel"
    if [ ! -f "$b" ] || ! cmp -s "$f" "$b"; then miss=$((miss+1)); fi
  done < <(find "$SKILL_SRC" -type f -print0)
  if [ -d "$CONSUMER_SKILL" ]; then
    while IFS= read -r -d '' f; do
      rel="${f#$CONSUMER_SKILL/}"
      [ "$rel" = "HARNESS_VERSION" ] && continue
      [ -f "$SKILL_SRC/$rel" ] || extra=$((extra+1))
    done < <(find "$CONSUMER_SKILL" -type f -print0)
  fi
  if [ "$miss" -eq 0 ] && [ "$extra" -eq 0 ]; then
    mark "$CN" T-V1 PASS "byte-identical (bidirectional)"
  else
    mark "$CN" T-V1 FAIL "miss=$miss extra=$extra"
  fi

  # ---- T-V2 provenance ----
  HV="$CONSUMER_SKILL/HARNESS_VERSION"
  if [ -f "$HV" ]; then
    content="$(<"$HV")"
    if [[ "$content" =~ ^[0-9a-f]{40}$ ]]; then
      mark "$CN" T-V2 PASS "${content:0:7}"
    else
      mark "$CN" T-V2 FAIL "non-SHA: $(printf '%s' "$content" | head -c 50)"
    fi
  else
    mark "$CN" T-V2 FAIL "absent"
  fi

  # ---- T-V3 no submodule artifacts ----
  fails=()
  [ -e "$C/.harness" ] && fails+=(".harness exists")
  if [ -f "$C/.gitmodules" ] && grep -q 'path = .harness' "$C/.gitmodules"; then
    fails+=(".gitmodules lists .harness")
  fi
  while IFS= read -r -d '' s; do
    if [ ! -e "$s" ]; then fails+=("broken-symlink:${s#$C/}"); fi
  done < <(find "$C/.claude/skills" -maxdepth 2 -type l -print0 2>/dev/null)
  # skill-creator itself must be a real dir, not a symlink
  if [ -L "$CONSUMER_SKILL" ]; then fails+=("skill-creator is a symlink"); fi
  if [ "${#fails[@]}" -eq 0 ]; then
    mark "$CN" T-V3 PASS "clean"
  else
    mark "$CN" T-V3 FAIL "$(IFS=,;echo "${fails[*]}")"
  fi

  # ---- T-V4 skill discoverable (stricter — CR-9) ----
  SMD="$CONSUMER_SKILL/SKILL.md"
  if [ -f "$SMD" ]; then
    # Extract frontmatter strictly
    name="$(awk '/^---$/{f++;next} f==1 && /^name: /{sub(/^name: */,""); print; exit}' "$SMD")"
    desc="$(awk '/^---$/{f++;next} f==1 && /^description: /{sub(/^description: */,""); print; exit}' "$SMD")"
    if [ -n "$name" ] && [ -n "$desc" ]; then
      mark "$CN" T-V4 PASS "name=$name"
    else
      mark "$CN" T-V4 FAIL "name='$name' desc len=${#desc}"
    fi
  else
    mark "$CN" T-V4 FAIL "SKILL.md absent"
  fi

  # ---- T-V8 no leaked artifacts ----
  bad="$(find "$CONSUMER_SKILL" \( -name '.git' -o -name '.DS_Store' -o -name '__pycache__' -o -name '*.pyc' \) -print 2>/dev/null | head -5)"
  if [ -z "$bad" ]; then mark "$CN" T-V8 PASS "clean"
  else mark "$CN" T-V8 FAIL "$(echo "$bad" | tr '\n' ',')"; fi

  # ---- T-V9 deferred to consumer CI ----
  mark "$CN" T-V9 DEFER "consumer CI"

  # ---- T-V10 atomic PR scope (CR-5: real check when base provided) ----
  base="$(get_t_v10_base "$CN")"
  if [ -n "$base" ] && git -C "$C" rev-parse --verify -q "$base" >/dev/null 2>&1; then
    # Only these paths may appear in the diff:
    allowed='^(.gitmodules|.harness|.claude/skills/skill-creator(/|$))'
    bad_paths="$(git -C "$C" diff --name-only "$base"..HEAD | grep -Ev "$allowed" || true)"
    if [ -z "$bad_paths" ]; then
      mark "$CN" T-V10 PASS "scope clean vs $base"
    else
      mark "$CN" T-V10 FAIL "out-of-scope paths: $(echo "$bad_paths" | tr '\n' ',')"
    fi
  else
    mark "$CN" T-V10 N/A "set T_V10_BASE_$CN=<ref> to gate"
  fi

  # ---- T-V11 shared agent guidance ----
  agent_miss=0
  for D in "${DOCS[@]}"; do
    if [ ! -f "$C/docs/$D" ] || ! cmp -s "$HARNESS_ROOT/docs/$D" "$C/docs/$D"; then
      agent_miss=$((agent_miss+1))
    fi
  done
  for F in "${ROOT_AGENT_FILES[@]}"; do
    if [ ! -f "$C/$F" ] || ! grep -q 'docs/AGENT-GUIDE\.ko\.md' "$C/$F"; then
      agent_miss=$((agent_miss+1))
    fi
  done
  if [ "$agent_miss" -eq 0 ]; then
    mark "$CN" T-V11 PASS "agent guide current + root entrypoints reference it"
  else
    mark "$CN" T-V11 FAIL "missing_or_drifted=$agent_miss"
  fi
done

# ============================================================
# Harness-side tests
# ============================================================

# ---- T-V5 sync script integrity ----
if bash -n scripts/sync.sh 2>/dev/null && \
   grep -q -- '--check'  scripts/sync.sh && \
   grep -q -- '--commit' scripts/sync.sh; then
  mark "(harness)" T-V5 PASS "syntax + --check + --commit modes"
else
  mark "(harness)" T-V5 FAIL "syntax or mode missing"
fi

# ---- T-V6 drift detection (CR-3: trap-guarded, runs in subshell on first vendored consumer) ----
( set +e
  TARGET=""
  for C in "${CONSUMERS[@]}"; do
    [ -f "$C/.claude/skills/skill-creator/SKILL.md" ] && \
      [ ! -L "$C/.claude/skills/skill-creator" ] && { TARGET="$C"; break; }
  done
  if [ -z "$TARGET" ]; then
    echo "(harness)|T-V6|N/A|no vendored consumer to test drift against"
    exit 0
  fi
  SMD="$TARGET/.claude/skills/skill-creator/SKILL.md"
  TN="$(basename "$TARGET")"
  # snapshot
  ORIG="$(mktemp)"
  cp "$SMD" "$ORIG"
  trap 'cp "$ORIG" "$SMD"; rm -f "$ORIG"' EXIT INT TERM
  # introduce drift
  echo "# T-V6-drift-marker" >> "$SMD"
  bash scripts/sync.sh --check >/dev/null 2>&1; rc=$?
  # restore via trap; force check
  cp "$ORIG" "$SMD"
  bash scripts/sync.sh --check >/dev/null 2>&1; rc_after=$?
  if [ "$rc" -ne 0 ] && [ "$rc_after" -eq 0 ]; then
    echo "(harness)|T-V6|PASS|detected drift on $TN; clean after restore"
  else
    echo "(harness)|T-V6|FAIL|rc_drift=$rc rc_clean=$rc_after"
  fi
) > /tmp/t-v6-result.$$ 2>&1
T6LINE="$(grep '^(harness)|T-V6|' /tmp/t-v6-result.$$ | head -1)"
rm -f /tmp/t-v6-result.$$
if [ -n "$T6LINE" ]; then
  IFS='|' read -r tc tt ts tn <<<"$T6LINE"
  mark "$tc" "$tt" "$ts" "$tn"
else
  mark "(harness)" T-V6 FAIL "subshell produced no output"
fi

# ---- T-V7 idempotency (CR-1 + HIGH-1: atomic, race-free consumers.txt swap) ----
# Atomic swap pattern: backup the original via hardlink (or copy if hardlink fails),
# install temp consumer list via mv (atomic), then restore via mv. Outer-scope trap
# guarantees restoration regardless of how the subshell terminates (incl. SIGKILL).
TMPDIR_T7="$(mktemp -d)"
TMP_CONSUMER="$TMPDIR_T7/fake-consumer"
ORIG_BACKUP="$TMPDIR_T7/consumers.orig"
LOCAL_STASH="$TMPDIR_T7/consumers.local.stash"
mkdir -p "$TMP_CONSUMER/.claude/skills"
cp -p tests/consumers.txt "$ORIG_BACKUP"
# Stash any developer-local override so the consumers.txt swap actually drives
# sync.sh during the test. Without this, T-V7 reads .local.txt and the swap is
# a no-op — false PASS on machines with a local list.
HAD_LOCAL_T7=0
if [ -f tests/consumers.local.txt ]; then
  HAD_LOCAL_T7=1
  mv -f tests/consumers.local.txt "$LOCAL_STASH"
fi
echo "$TMP_CONSUMER" > "$TMPDIR_T7/temp-list.txt"

# OUTER-scope trap: fires on any exit path (incl. signals) before sub-tests of T-V7
_t7_restore() {
  [ -f "$ORIG_BACKUP" ] && mv -f "$ORIG_BACKUP" tests/consumers.txt 2>/dev/null
  [ "$HAD_LOCAL_T7" -eq 1 ] && [ -f "$LOCAL_STASH" ] && \
    mv -f "$LOCAL_STASH" tests/consumers.local.txt 2>/dev/null
  rm -rf "$TMPDIR_T7" 2>/dev/null
}
trap _t7_restore EXIT INT TERM

# Atomic swap-in (mv is atomic on the same filesystem)
mv -f "$TMPDIR_T7/temp-list.txt" tests/consumers.txt

# First apply
bash scripts/sync.sh >/dev/null 2>&1; rc1=$?
# Second apply should be no-op for content
bash scripts/sync.sh >/dev/null 2>&1; rc2=$?
# And --check should be clean
bash scripts/sync.sh --check >/dev/null 2>&1; rcheck=$?

# Restore (atomic) before recording result — trap also covers abnormal exits
mv -f "$ORIG_BACKUP" tests/consumers.txt
if [ "$HAD_LOCAL_T7" -eq 1 ] && [ -f "$LOCAL_STASH" ]; then
  mv -f "$LOCAL_STASH" tests/consumers.local.txt
fi
trap - EXIT INT TERM  # disarm trap; we're done with the swap

if [ "$rc1" -eq 0 ] && [ "$rc2" -eq 0 ] && [ "$rcheck" -eq 0 ]; then
  mark "(harness)" T-V7 PASS "second apply no drift; consumers.txt atomically swapped"
else
  mark "(harness)" T-V7 FAIL "rc1=$rc1 rc2=$rc2 rcheck=$rcheck"
fi
rm -rf "$TMPDIR_T7" 2>/dev/null || true

# ---- T-V12 harness-local skill registration ----
# Every skills/<name>/ must have a correct .claude/skills/<name> symlink in THIS
# repo. Delegates to scripts/register-skills.sh --check so the rule lives in one
# place (the generator) and cannot drift from what apply produces. This is the
# coverage gap that let #28 ship skills/hype-review/ with no symlink.
if reg_out="$(bash scripts/register-skills.sh --check 2>&1)"; then
  mark "(harness)" T-V12 PASS "every skills/ has a .claude/skills/ symlink"
else
  mark "(harness)" T-V12 FAIL "$(printf '%s' "$reg_out" | grep '^DRIFT' | tr '\n' ';' | head -c 200)"
fi

# ---- T-V13 weekly-loop asset family registered & coherent ----
# The weekly operating loop ships as doc + skill + scripts; a partial
# registration (e.g. skill without scripts, or assets missing from sync.sh
# arrays) would vendor a broken loop to all three consumers. Harness-side
# check — needs no consumer.
t13_fails=()
[ -f docs/WEEKLY-LOOP.ko.md ] || t13_fails+=("docs/WEEKLY-LOOP.ko.md absent")
for wf in scripts/weekly-harness/check.py scripts/weekly-harness/burndown.py; do
  [ -f "$wf" ] || t13_fails+=("$wf absent")
done
WLMD="skills/weekly-loop/SKILL.md"
if [ -f "$WLMD" ]; then
  wl_name="$(awk '/^---$/{f++;next} f==1 && /^name: /{sub(/^name: */,""); print; exit}' "$WLMD")"
  wl_desc="$(awk '/^---$/{f++;next} f==1 && /^description: /{sub(/^description: */,""); print; exit}' "$WLMD")"
  { [ -n "$wl_name" ] && [ -n "$wl_desc" ]; } || t13_fails+=("SKILL.md frontmatter incomplete")
else
  t13_fails+=("$WLMD absent")
fi
grep -qE '^SKILLS=\(.*weekly-loop'          scripts/sync.sh || t13_fails+=("weekly-loop not in SKILLS=()")
grep -qE '^DOCS=\(.*WEEKLY-LOOP\.ko\.md'    scripts/sync.sh || t13_fails+=("WEEKLY-LOOP.ko.md not in DOCS=()")
grep -qE '^SCRIPTS=\(.*weekly-harness'      scripts/sync.sh || t13_fails+=("weekly-harness not in SCRIPTS=()")
if [ "${#t13_fails[@]}" -eq 0 ]; then
  mark "(harness)" T-V13 PASS "doc + skill + scripts present and registered in sync.sh"
else
  mark "(harness)" T-V13 FAIL "$(IFS=';'; echo "${t13_fails[*]}")"
fi

# ---- T-V14 run.sh doc-fidelity list is derived from sync.sh, not hardcoded ----
# Regression guard for #47: the two DOCS lists used to diverge (run.sh silently
# skipped drift for docs added only to sync.sh). Assert run.sh derives its list
# from sync.sh and does not reintroduce a hardcoded doc-name array.
t14_fails=()
# 1. run.sh must parse sync.sh's DOCS=() array.
grep -q "grep -E '\^DOCS=" tests/run.sh || t14_fails+=("run.sh does not derive DOCS from sync.sh")
# 2. run.sh must not hardcode a doc-name list (no *.ko.md literal on a DOCS= line).
if grep -nE '^\s*DOCS=\([^)]*\.ko\.md' tests/run.sh >/dev/null; then
  t14_fails+=("run.sh reintroduced a hardcoded DOCS=() doc list")
fi
# 3. The derived list must actually cover every doc sync.sh vendors.
_sd_line="$(grep -E '^DOCS=\(' scripts/sync.sh | head -1)"; _sd_inner="${_sd_line#*(}"; _sd_inner="${_sd_inner%%)*}"
# shellcheck disable=SC2206
_sync_docs=($_sd_inner)
for _d in "${_sync_docs[@]}"; do
  covered=0
  for _c in "${DOCS[@]}"; do [ "$_c" = "$_d" ] && covered=1 && break; done
  [ "$covered" -eq 1 ] || t14_fails+=("$_d vendored by sync.sh but not covered by the gate")
done
unset _sd_line _sd_inner _sync_docs _d _c covered
if [ "${#t14_fails[@]}" -eq 0 ]; then
  mark "(harness)" T-V14 PASS "run.sh DOCS derived from sync.sh; all vendored docs covered"
else
  mark "(harness)" T-V14 FAIL "$(IFS=';'; echo "${t14_fails[*]}")"
fi

# ============================================================
# Output
# ============================================================
echo
echo "## Vendor migration tests — harness@${HARNESS_SHA:0:7}"
echo
printf "| Consumer | Test | Result | Note |\n|---|---|---|---|\n"
for r in "${RESULTS[@]}"; do
  IFS='|' read -r c t s n <<<"$r"
  printf "| %s | %s | %s | %s |\n" "$c" "$t" "$s" "$n"
done
echo
echo "Totals: PASS=$PASS · FAIL=$FAIL · DEFER=$DEFER · SKIP=$SKIP · N/A=$NA"
echo "Consumers found: $N_CONSUMERS_FOUND / ${#CONSUMERS[@]}"

if [ "$N_CONSUMERS_FOUND" -eq 0 ]; then
  {
    echo ""
    echo "✗ No consumer repos found — every path in tests/consumers.txt was missing."
    echo "  Resolve one of: clone consumers as siblings of hypeproof-harness (zero-config),"
    echo "  export HYPEPROOF_WORKSPACE=/abs/path, or set CONSUMER_<repo>=/abs/path."
    echo "  HYPEPROOF_WORKSPACE currently resolves to: $HYPEPROOF_WORKSPACE"
  } >&2
fi

# JSON
{
  echo '{'
  echo "  \"harness_sha\": \"$HARNESS_SHA\","
  echo "  \"consumers_total\": ${#CONSUMERS[@]},"
  echo "  \"consumers_found\": $N_CONSUMERS_FOUND,"
  echo "  \"totals\": {\"pass\": $PASS, \"fail\": $FAIL, \"defer\": $DEFER, \"skip\": $SKIP, \"na\": $NA},"
  echo '  "results": ['
  last_idx=$((${#RESULTS[@]} - 1))
  for i in "${!RESULTS[@]}"; do
    IFS='|' read -r c t s n <<<"${RESULTS[$i]}"
    sep=$([ "$i" -lt "$last_idx" ] && echo "," || echo "")
    # escape backslashes and double quotes in note
    n_esc="$(printf '%s' "$n" | sed 's/\\/\\\\/g; s/"/\\"/g')"
    printf '    {"consumer":"%s","test":"%s","result":"%s","note":"%s"}%s\n' "$c" "$t" "$s" "$n_esc" "$sep"
  done
  echo '  ]'
  echo '}'
} > tests/last-report.json

# ============================================================
# Gate (CR-5: DEFER alone must not exit 0)
# Required: 6 per-consumer PASSes (T-V1..T-V4, T-V8, T-V11) × N_CONSUMERS_FOUND
#         + 5 harness PASSes always (T-V5, T-V7, T-V12, T-V13, T-V14) + T-V6 if applicable
# T-V6 may be N/A if no consumer is vendored yet — relax in that case.
# T-V9 always DEFER (consumer CI), T-V10 may be N/A (no base ref).
# ============================================================
required=$(( N_CONSUMERS_FOUND * 6 ))
# T-V5 always counts
required=$((required + 1))
# T-V6 only counts if it produced PASS/FAIL (not N/A)
if grep -q '^(harness)|T-V6|PASS$\|^(harness)|T-V6|FAIL' <(printf '%s\n' "${RESULTS[@]}"); then
  required=$((required + 1))
fi
# T-V7 always counts
required=$((required + 1))
# T-V12 always counts
required=$((required + 1))
# T-V13 always counts
required=$((required + 1))
# T-V14 always counts
required=$((required + 1))

echo "Gate: PASS=$PASS required>=$required FAIL=$FAIL SKIP=$SKIP"
if [ "$FAIL" -eq 0 ] && [ "$SKIP" -eq 0 ] && [ "$PASS" -ge "$required" ]; then
  echo "✓ PASS — gate satisfied"
  exit 0
else
  echo "✗ FAIL — gate not satisfied"
  exit 1
fi
