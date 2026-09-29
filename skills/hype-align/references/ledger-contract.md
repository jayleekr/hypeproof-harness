# hype-align ledger contract

The rules `scripts/align.py` applies. Anything not stated here is decided by the canonical
`scripts/work-discovery/discover.py` (spec: `docs/WORK-DISCOVERY.ko.md`).

Contents: 1 Inputs · 2 next · 3 Requirement rows · 4 record · 5 check · 6 drift

## 1. Inputs

| Input | Where | Notes |
|---|---|---|
| Ledger | `<studio>/config/requirement-work.json` | loaded with `discover.load_manifest` |
| Integrity | `discover.audit` | missing/changed documents, unassigned IDs, cycles |
| States | `discover.classify` | ready, claimed, in_review, dependency, blocked, reconcile, complete |
| Completion | `discover.fulfilled`, `discover.scope_digest` | the only definition of complete |
| Testing documents | `<studio>/docs/testing/**/*.md` | plus each document's registered `test` path |
| Lab catalog | `<lab>/web/scripts/lib/studio_catalog.mjs` | `catalogSources`, `excludedSources` |
| Lab features | `<lab>/web/src/content/private/studio-prd/{features.ts,work.json,catalog.json}` | |

Files are read from the working tree, not from a commit. Use a clean worktree.

## 2. next

1. `discover.audit` runs first. Any gap makes the verdict "reconcile the requirement ledger
   first" and the exit code 1; the ranking is still printed as advice.
2. States come from `discover.classify` with a GitHub snapshot:
   - default: offline. Every tracked issue is treated as open, with no PRs and no claims.
     The output says `availability: unchecked`.
   - `--snapshot FILE`: a snapshot saved by `discover.py --save-snapshot` (max age 1 h).
   - `--live`: `discover.live_snapshot` through `gh`.
3. Scope filters (`--item`, `--doc`, `--prefix`) apply after classification, so a dependency
   outside the scope still blocks an item inside it.
4. Ready items sort by this key, smallest first:

   | Order | Key | Source |
   |---|---|---|
   | 1 | depth | longest `depends_on` chain above the item in the whole ledger (0 = root) |
   | 2 | priority | best `P<n>` among the requirement rows the item cites; none sorts last |
   | 3 | curriculum week | item field `curriculum_week` (int or list), else the earliest row week tag; none sorts last |
   | 4 | ledger order | position in `work_items` |

   The first item is `next`; the whole list is `ranked`.

## 3. Requirement rows

A requirement row is a Markdown table line whose first cell is the ID, the same shape
`discover.requirement_ids` accepts (`| CR-01 | ... |`, optional backticks). Heading-style
(`### VO-01`) and inline IDs have no row, so no priority, week or cited test.

- **Priority**: the first cell that starts with `P0`..`P9` (not `P0-5`). Examples that parse:
  `| P0 |`, `| P0 / INT-CR-01 |`, `| P1 / W2 / INT-CR-03 |`.
- **Week tag**: in that priority cell, `W<n>`, `Week <n>` or `<n>주차`; or a cell that holds
  only week tags (`| W1 |`, `| Week 2 |`, `| W1–W2 |`). Free text elsewhere is ignored, so
  an acceptance sentence quoting "3주차" does not tag the row. The earliest week wins.
- **Cited tests**: every `-T<n>` token in the row's cells.

### Test-ID grammar

`PREFIX-T<n>` with shorthand continuations that expand with the same prefix and width:
`CA-T16/17` → CA-T16, CA-T17 · `SX-T02·03` → SX-T02, SX-T03 · `SX-T52~57` or `..` or `–` → the range.
Commas do not continue a list. A token must not be preceded by a letter, digit or hyphen,
so `INT-ACCESS-01` is not `SS-01`. Requirement-ID mentions expand the same way (`AE-01/02`).

A test ID is **defined** when a testing document under `docs/testing/` contains it as a
`-T<n>` token or as the first cell of a table row (some documents key tests by the
requirement ID). A registered test document outside `docs/testing/` defines only `-T<n>` tokens.

A requirement has a **test link** when its row cites a test, or:
- its registered test document (when it is a different file) names the requirement, or
- any `docs/testing/` document names it and the ID's prefix belongs to one registered document, or
- its tests live in the requirement document itself and a line other than its own row names
  both the requirement and a `-T<n>` test.

## 4. record

`record <item>` writes `work_items[i].completion` and, with `--input`, extends
`verification_inputs`. Nothing else in the ledger changes. The file is rewritten as
`json.dumps(indent=2, ensure_ascii=False)` plus a newline, which is the ledger's own format.

```json
"completion": {
  "verdict": "PASS",
  "reviewed_by": "independent verifier",
  "report": "docs/testing/evidence/cr-browser.md",
  "scope_sha256": "<discover.scope_digest of the packet as recorded>",
  "inputs": {"<requirement doc>": "<sha256>", "<verification input>": "<sha256>", "<report>": "<sha256>"},
  "commit": "<merge commit SHA>",
  "test_ids": ["CR-T01", "CR-T02"],
  "recorded_at": "2026-09-29T08:00:00Z",
  "pr": 1402
}
```

The first five fields are what `discover.fulfilled` judges. `commit`, `test_ids`,
`recorded_at` and optional `pr` are provenance for people and for `check`; discover.py
ignores them.

Refusals (exit 1, nothing written):

| Condition | Why |
|---|---|
| `--tests` empty, or a test ID not defined (§3) | no test result, no completion |
| `--evidence` missing, not a file, outside the checkout, or the ledger itself | the report must be pinned and travel with the repo |
| `--reviewed-by` empty | discover.py requires an attesting reviewer |
| `--commit` not 7–40 hex, or unknown to a git checkout | the record must point at a real delivered revision |
| item already complete without `--replace` | a verdict is superseded deliberately, not by accident |
| no `verification_inputs` after `--input` | discover.py never counts a requirement-only completion |
| discover.py would not classify the result complete | the record would be dead on arrival |
| any broken link from §5 for this item (Lab excluded) | `record` never writes what `check` rejects |

## 5. check

Broken links (exit 1):

| Kind | Meaning |
|---|---|
| `requirement-doc` | a cited path is not a registered document or does not exist |
| `requirement` | a cited ID is not defined in its document (`discover.requirement_ids`) |
| `intent` / `design` / `test-doc` | the document's registered intent, design or test file is missing |
| `test-id` | a row cites a test ID that no testing document defines |
| `test-link` | none of the item's requirements has a test link, and no completion test IDs |
| `completion` | a completion lacks test IDs, cites an undefined test, lost its evidence, or no longer holds under `discover.fulfilled` |
| `implementation` | an item with a completion has no `implementation_paths`, or one does not exist |
| `lab` | with `--lab`: neither `work.json` (item id or issue) nor `features.ts` (document slug plus one of its IDs, or the whole document) links the item |
| `lab-feature` | with `--lab`: an item `feature_ids` entry is not a feature in `features.ts` |

Warnings (exit unaffected): `untested-requirement` for each cited requirement without a
test link, when the item as a whole still has one.

## 6. drift

Compares, on disk:

- Lab `catalogSources` (paths from the `path:` template, default `docs/requirements/<slug>.md`)
  and `excludedSources`,
- Studio `docs/requirements/**/*.md` (recursive, as the Lab sync script lists it),
- the ledger's `documents` and `excluded`.

| Finding | Meaning |
|---|---|
| `unclassified` | a Studio document the Lab neither lists nor excludes; the detail says whether the ledger registers or excludes it |
| `removed` | the Lab lists or excludes a document Studio no longer has |
| `classification` | the Lab and the ledger disagree: one shows what the other excludes |
| `stale` | a pinned Lab `catalog.json` source differs from the Studio file: document, evidence, excluded document, or plan (added, removed, changed) |

Hashes follow the Lab sync script: SHA-256 of the file text after JavaScript `trim()`.
A different `sourceCommit` alone is not drift; the pin line reports how many commits
behind it is when the checkout knows that commit.
