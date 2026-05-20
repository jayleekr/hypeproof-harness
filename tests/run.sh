#!/usr/bin/env bash
# tests/run.sh — execute T-V1..T-V10 (T-V10 partial) against each consumer.
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

# ----- consumer resolution (mirrors sync.sh) -----
expand_path() {
  local p="$1"
  case "$p" in *[\'\"\`\;\|\&]*) echo "$p"; return ;; esac
  eval "echo $p"
}
_sanitize() { echo "$1" | tr '-' '_'; }
get_env_override() { local v="CONSUMER_$(_sanitize "$1")"; echo "${!v:-}"; }
get_t_v10_base()   { local v="T_V10_BASE_$(_sanitize "$1")"; echo "${!v:-}"; }

CONSUMERS=()
while IFS= read -r raw; do
  raw="${raw%%#*}"; raw="${raw#"${raw%%[![:space:]]*}"}"; raw="${raw%"${raw##*[![:space:]]}"}"
  [ -z "$raw" ] && continue
  e="$(expand_path "$raw")"
  bn="$(basename "$e")"
  o="$(get_env_override "$bn")"
  [ -n "$o" ] && e="$o"
  CONSUMERS+=("$e")
done < tests/consumers.txt

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
  if [ "${#fails[@]:-0}" -eq 0 ]; then
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

# ---- T-V7 idempotency (CR-1: non-destructive — temp consumer) ----
TMPDIR_T7="$(mktemp -d)"
TMP_CONSUMER="$TMPDIR_T7/fake-consumer"
mkdir -p "$TMP_CONSUMER/.claude/skills"
# Use a throwaway consumers.txt for this test
TMP_CONS_LIST="$TMPDIR_T7/consumers.txt"
echo "$TMP_CONSUMER" > "$TMP_CONS_LIST"
( cp tests/consumers.txt "$TMPDIR_T7/_orig_cons.txt"
  cp "$TMP_CONS_LIST" tests/consumers.txt
  trap 'cp "$TMPDIR_T7/_orig_cons.txt" tests/consumers.txt; rm -rf "$TMPDIR_T7"' EXIT INT TERM
  # first apply
  bash scripts/sync.sh >/dev/null 2>&1
  # snapshot mtimes
  m1="$(find "$TMP_CONSUMER" -type f -exec stat -f '%m %N' {} \; 2>/dev/null | sort)"
  sleep 1
  # second apply should be a no-op for content (rsync -a updates only changed)
  bash scripts/sync.sh >/dev/null 2>&1
  m2="$(find "$TMP_CONSUMER" -type f -exec stat -f '%m %N' {} \; 2>/dev/null | sort)"
  # And --check should be clean
  bash scripts/sync.sh --check >/dev/null 2>&1; rcheck=$?
  changed="$(diff <(echo "$m1") <(echo "$m2") | head -3)"
  if [ "$rcheck" -eq 0 ]; then
    echo "(harness)|T-V7|PASS|second apply produced no content drift (rsync -a)"
  else
    echo "(harness)|T-V7|FAIL|--check after sync returned $rcheck"
  fi
) > /tmp/t-v7-result.$$ 2>&1
T7LINE="$(grep '^(harness)|T-V7|' /tmp/t-v7-result.$$ | head -1)"
rm -f /tmp/t-v7-result.$$
if [ -n "$T7LINE" ]; then
  IFS='|' read -r tc tt ts tn <<<"$T7LINE"
  mark "$tc" "$tt" "$ts" "$tn"
else
  mark "(harness)" T-V7 FAIL "T-V7 subshell produced no output"
fi
# defensive: restore consumers.txt if subshell trap didn't fire
if [ -f "$TMPDIR_T7/_orig_cons.txt" ]; then
  cp "$TMPDIR_T7/_orig_cons.txt" tests/consumers.txt 2>/dev/null || true
fi
rm -rf "$TMPDIR_T7" 2>/dev/null || true

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
# Required: 5 per-consumer PASSes (T-V1..T-V4, T-V8) × N_CONSUMERS_FOUND
#         + 3 harness PASSes (T-V5, T-V6 if applicable, T-V7)
# T-V6 may be N/A if no consumer is vendored yet — relax in that case.
# T-V9 always DEFER (consumer CI), T-V10 may be N/A (no base ref).
# ============================================================
required=$(( N_CONSUMERS_FOUND * 5 ))
# T-V5 always counts
required=$((required + 1))
# T-V6 only counts if it produced PASS/FAIL (not N/A)
if grep -q '^(harness)|T-V6|PASS$\|^(harness)|T-V6|FAIL' <(printf '%s\n' "${RESULTS[@]}"); then
  required=$((required + 1))
fi
# T-V7 always counts
required=$((required + 1))

echo "Gate: PASS=$PASS required>=$required FAIL=$FAIL SKIP=$SKIP"
if [ "$FAIL" -eq 0 ] && [ "$SKIP" -eq 0 ] && [ "$PASS" -ge "$required" ]; then
  echo "✓ PASS — gate satisfied"
  exit 0
else
  echo "✗ FAIL — gate not satisfied"
  exit 1
fi
