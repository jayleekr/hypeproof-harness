# Vendor Migration — Test Requirements (T-V1 ... T-V14)

Acceptance criteria for migrating the three HypeProof consumer repos from
`.harness` submodule + symlink to **vendored real files** for the shared
`skill-creator`. Tests are bash + standard Unix tools; runnable from the
harness repo against any consumer path.

## System under test

- **Canonical source**: `hypeproof-harness:skills/skill-creator/` (this repo).
- **Consumers**: `hypeproof-studio` · `sediment` · `hypeprooflab` — each
  vendors `.claude/skills/skill-creator/*` as real files + a
  `.claude/skills/skill-creator/HARNESS_VERSION` provenance marker
  containing the 40-char SHA of harness HEAD at sync time.
- **Sync mechanism**: `scripts/sync.sh` — apply (rsync), `--check`
  (read-only drift), `--commit` (apply + branch/clean-tree-guarded git
  commit in each consumer). Identity comes from the consumer repo's own
  git config — the script never overrides `user.name` / `user.email`.
- **Agent guidance**: `docs/AGENT-GUIDE.ko.md` is the canonical shared
  agent policy. Root `CLAUDE.md`, `AGENTS.md`, and `OPENCLAW.md` are thin
  entrypoints vendored to consumers so Claude Code, Codex, OpenClaw, and
  future agents read the same rules.

## Test IDs

| ID | Property | Pass condition |
|---|---|---|
| **T-V1** | Content fidelity (bidirectional) | For every file in `harness/skills/skill-creator/`, the consumer copy is byte-identical, AND the consumer has no extra files beyond `HARNESS_VERSION`. |
| **T-V2** | Provenance present | Each consumer has `.claude/skills/skill-creator/HARNESS_VERSION` containing the 40-char SHA of the harness HEAD that produced it. |
| **T-V3** | No submodule artifacts | `.gitmodules` does not list `.harness`; no `.harness/` directory exists; `.claude/skills/skill-creator` is a real directory (not a symlink); no broken symlinks under `.claude/skills/`. |
| **T-V4** | Skill discoverable | `.claude/skills/skill-creator/SKILL.md` exists; YAML frontmatter has non-empty `name:` and non-empty `description:`. |
| **T-V5** | Sync script integrity | `scripts/sync.sh` passes `bash -n`; supports `--check` and `--commit` modes. |
| **T-V6** | Drift detection | Artificially modifying a vendored consumer file makes `sync.sh --check` exit non-zero and name the drift; after restore it exits zero. Test runs trap-guarded against a real vendored consumer; safe on Ctrl-C. |
| **T-V7** | Idempotency | A second `sync.sh` apply against an unchanged consumer produces no drift detectable by `--check`. **Test runs against a temp directory — never touches real consumer repos.** |
| **T-V8** | No leaked artifacts | Vendored tree contains no `.git`, `.DS_Store`, `__pycache__`, `*.pyc`. |
| **T-V9** | No regression (CI) | Each consumer's existing test gate (studio main-guard / sediment validator / lab ci.yml) does not fail because of the migration. Always reported as DEFER from the harness; check the PR's CI status manually. |
| **T-V10** | Atomic PR scope (per-consumer, env-gated) | When `T_V10_BASE_<consumer>` env var is set to a ref (e.g. pre-migration HEAD), `git diff --name-only $BASE..HEAD` in that consumer contains only paths under `.gitmodules`, `.harness`, or `.claude/skills/skill-creator`. If env var unset, reported as N/A (not gated). |
| **T-V11** | Shared agent guidance | `docs/MEMBER-GUIDE.ko.md` and `docs/AGENT-GUIDE.ko.md` are byte-identical to harness canonical sources. `CLAUDE.md`, `AGENTS.md`, and `OPENCLAW.md` are present and reference `docs/AGENT-GUIDE.ko.md`; existing consumer-specific content is preserved. |
| **T-V12** | Harness-local skill registration | In the harness repo itself, every `skills/<name>/` has a `.claude/skills/<name>` symlink → `../../skills/<name>` that resolves, and no orphaned harness symlink points to a missing skill. Delegates to `scripts/register-skills.sh --check` so the rule has a single source of truth (the generator) and `--check` never disagrees with what `apply` produces. Harness-side check — needs no consumer. |
| **T-V13** | Weekly-loop asset family registered & coherent | The weekly operating loop's three assets all exist in the harness — `docs/WEEKLY-LOOP.ko.md`, `skills/weekly-loop/SKILL.md` (frontmatter with non-empty `name:` + `description:`), `scripts/weekly-harness/check.py` + `burndown.py` — AND all three are registered in `scripts/sync.sh` (`SKILLS=()`, `DOCS=()`, `SCRIPTS=()` respectively), so a partial registration can never vendor a broken loop. Behavioral coverage lives in `tests/weekly_loop/` (pytest, CI). Harness-side check — needs no consumer. |
| **T-V14** | run.sh doc-fidelity list derived from sync.sh | The gate's `DOCS` list is derived at runtime from `scripts/sync.sh`'s `DOCS=()` array, never hardcoded, so the two can't diverge (the drift that motivated #47). Asserts run.sh parses sync.sh's `DOCS=()`, reintroduces no hardcoded `DOCS=(…*.ko.md…)` literal, and covers every doc sync.sh vendors. Harness-side check — needs no consumer. |

## Pass/fail aggregation (CR-5 fixed)

`tests/run.sh` exits non-zero unless:

- `FAIL = 0`, AND
- `SKIP = 0` (every consumer path resolves), AND
- `PASS >= 6N + 4 + [T-V6 if applicable]`
  - N = number of consumers found
  - 6 per-consumer required PASSes: T-V1, T-V2, T-V3, T-V4, T-V8, T-V11
  - 5 harness PASSes always: T-V5, T-V7, T-V12, T-V13, T-V14
  - + T-V6 when a vendored consumer exists to test drift against (else N/A, not required)
- DEFER (T-V9, T-V10 unconfigured) does **not** count as PASS.

## Portability (CR-2 fixed)

`tests/consumers.txt` lines support `~` and `${VAR}` expansion and carry no
machine-specific absolute paths. Resolution order:

1. **`tests/consumers.local.txt`** — if this file exists, it replaces
   `consumers.txt` as the source of the consumer list. Gitignored; see
   `tests/consumers.local.example`. Lets a member with only some consumers
   cloned run a partial gate green, and lets a maintainer with an unusual
   checkout layout point paths anywhere.
2. `CONSUMER_<basename>=<absolute-path>` env — per-repo override applied on
   top of whichever list was loaded, e.g.
   ```bash
   CONSUMER_hypeproof-studio=/Users/x/work/hps bash tests/run.sh
   ```
3. `${HYPEPROOF_WORKSPACE}` — base for `${HYPEPROOF_WORKSPACE}/<repo>` entries;
   `export` it to point at your workspace.
4. Default (zero-config): if `HYPEPROOF_WORKSPACE` is unset, both `sync.sh` and
   `tests/run.sh` set it to the **parent of this repo**, so consumers cloned as
   siblings of hypeproof-harness resolve without any env.

Missing consumer paths are reported as `SKIP` (counted as fail), never
silent-pass; when *no* consumer resolves at all, a hint naming the options
above is printed.

## T-V10 usage (CR-5)

After a consumer's migration commit lands, set the env var to the
pre-migration HEAD ref and re-run:

```bash
T_V10_BASE_hypeproof-studio=ef443a8 \
T_V10_BASE_sediment=107d400        \
T_V10_BASE_hypeprooflab=3db9ee7    \
bash tests/run.sh
```

## Rollback

See [docs/rollback-vendor.md](../docs/rollback-vendor.md) for the
concrete procedure to return to submodule architecture.

## Out of scope

- Performance of the sync script (~20 files of skill-creator).
- Multi-skill harness (we have one shared skill; `SKILLS=` array in
  sync.sh extends per-skill if needed).
- Full Claude Code skill-invocation E2E (covered by per-repo CI in T-V9).
