---
name: hype-align
description: "Decide the next HypeProof requirement work item and keep the requirement ledger, product docs and Lab feature catalog aligned. Runs deterministic next, record, check and drift verdicts over a product's config/requirement-work.json on top of the Harness work-discovery engine. Use it whenever a delivery slice starts and you need to know what to take next, when a slice has merged and its completion (commit, PR, test IDs, evidence) must be recorded in the ledger, when you need to know whether a work item's intent, requirement, design, test, implementation and Lab links are intact, or when the Lab /members/studio/features catalog may have drifted from Studio requirement documents, including requests phrased as 다음 작업, 완료 기록, 정렬 체크 or 드리프트. Not for opening PRs (hype-pr) or implementing a slice (hype-deliver)."
---

# HypeProof alignment verdicts

One run answers one question: the output ends with a single `Verdict:` line and the
exit code carries it (0 holds, 1 negative verdict or refusal, 2 could not evaluate).
The script reads files and writes only the ledger during `record`. It never commits,
never pushes, and reads GitHub only with `next --live`.

## Setup

- Script: `scripts/align.py` next to this file. Python 3.9+, standard library only.
- It loads the canonical `scripts/work-discovery/discover.py`: automatically inside
  hypeproof-harness; in a product repo from `HYPEPROOF_HARNESS` or a sibling
  `hypeproof-harness` checkout, skipping any that predates this skill. Everything about
  ledger integrity, issue/PR states and when a completion counts comes from that file,
  not from this skill.
- Product checkout: `--studio <path>` or `HYPEPROOF_STUDIO`. Point it at a worktree
  cut from current `origin/main`. A stale checkout gives a correct verdict about the
  wrong files.
- Lab checkout: `--lab <path>` (a hypeprooflab worktree) for `check` and `drift`.

## Commands

| Command | Question | Exit 1 means |
|---|---|---|
| `next` | Which ready work item comes first? | the ledger itself has gaps to reconcile first |
| `record <item>` | Write this item's completion into the ledger | refused: missing or unrelated tests, evidence, reviewer, an unmerged commit, open dependencies, uncommitted pins, ledger gaps or a broken link |
| `check` | Is the ledger intact, and every item's intent → requirement → design → test → implementation (→ Lab) chain? | a ledger gap or at least one broken link, listed per item |
| `drift` | Does the Lab catalog classify every Studio requirement document, and are its pinned sources current? | unclassified, removed, misclassified or stale sources |

```bash
A=<this skill>/scripts/align.py      # consumer repos: .claude/skills/hype-align/scripts/align.py
python3 $A next   --studio $S --doc curriculum-runtime          # add --json for machines
python3 $A record cr-browser --studio $S --commit <merge sha on main> --pr 1402 \
  --tests CR-T04,CR-T05 --evidence docs/evidence/cr-browser.md --reviewed-by <verifier>
python3 $A check  --studio $S --doc curriculum-runtime --lab $L
python3 $A drift  --studio $S --lab $L
```

`record` takes the evidence report from its own file: a registered test document is refused,
because only registered test documents define test IDs and a report must not define what it attests.
Every `--tests` ID must test a requirement the item cites (its row cites the test, or one line of a
test document names both).

`--item`, `--doc` (path, file name or stem) and `--prefix` narrow `next` and `check` to
one epic. Without them the whole ledger is ranked and checked.

## In the delivery loop

1. **Slice start.** Run `next` scoped to the epic. Take the `NEXT` item and read its packet
   (`next_action`, controls, `evidence_required`) before touching code. The default is
   offline: open PRs and `wip` claims were not read, so confirm the issue is free, or run
   with `--live` (spends GitHub API budget) or `--snapshot <discover.py snapshot>`.
2. **Slice end**, after merge and independent verification, in a worktree cut from the new
   `origin/main`: add the evidence report, run `record <item>` with `--commit` set to the squash
   commit on main, then `check --doc <epic> --lab <Lab>` (the whole epic, not only `--item`). `record` edits
   `config/requirement-work.json` and nothing else and never commits: commit the ledger and the
   report together and ship them through `hype-pr` like any change.
3. **Reopened completions.** A completion pins its requirement document, verification inputs and
   report by hash. When items share a pinned file (for example one epic testing document in every
   `verification_inputs`), the next slice's edit to it reopens every earlier completion that pins
   it: `check` reports `completion no longer holds (changed since recorded: <file>)` and `next`
   names the earlier item again. Verify those items against the new content and re-record them with
   `--replace`. `record` warns when it pins a file other items pin; prefer per-slice
   `verification_inputs` (the slice's implementation and test files) over a shared epic document.
4. **Catalog sync.** Run `drift` before a Lab studio-catalog sync and after one; every
   finding names the document and what to classify or refresh.

## Reading the verdicts

- `ready` means the ledger allows the item now. It is not acceptance, and zero ready items
  is not evidence the scope is complete: read the state counts.
- Offline `next` (the default) treats every tracked issue as open: a closed issue without a
  completion ranks as ready where `--live` would say reconcile. `--json` carries
  `availability_checked: false` for this case, and `{"verdict", "error"}` on a refusal or exit 2.
- `complete` is discover.py's rule: a PASS completion whose scope digest and pinned input
  hashes still match. Editing a pinned file or the packet's acceptance fields reopens it,
  and `check` reports it as `completion no longer holds`.
- `check` warnings (`untested-requirement`) do not fail the run; report them as debt,
  separately from the gate result.
- `record` refuses rather than writing a record that `check` would call broken.

Exact rules (ranking key, priority and week tags, test-ID grammar, completion schema,
link kinds, drift semantics) are in [references/ledger-contract.md](references/ledger-contract.md).
Read it before changing a requirement table format or the completion fields.

Report outcomes to Jay in Korean; keep ledger fields, commit messages and PR bodies in English.
