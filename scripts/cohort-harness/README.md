# cohort-harness

> Guardrail validator for HypeProof Studio **cohort profiles**. Pure Python
> standard library (no package manager). Vendored from `hypeproof-harness`
> into every consumer repo via `sync.sh`. The check *engine* lives here; the
> *guardrails* live in `rules.yaml` as data.

## Why

A studio cohort = one `Profile` object (`worker/src/profiles/<id>.ts`) that
defines the whole in-app coaching UX without code changes. `tsc` proves the
profile is well-*typed* — it cannot prove it is *safe* or *coherent*:

- an asset-name typo (`"creativty"`) is a valid string to TypeScript;
- a child cohort with `analytics.log_user_messages: true` compiles fine but is
  a privacy violation;
- a `system_prompt` that promises "publish to the internet" while
  `publishing.enabled: false` is a contradiction no compiler catches;
- two profiles in the same `cohort_id` disagreeing on `series_total` typechecks.

These only surfaced **at the workshop**. `COHORT-AUTHORING.md §보안/가드레일`
documented them as prose. This harness turns that prose into an executable gate.

Mirrors `scripts/docs-harness/check.py`: a stdlib validator that consumes
**data, not consumer code**. Studio dumps its profiles to JSON; the rule engine
is canonical here and shared by every product.

## How

```
# studio (domain) dumps profiles → harness (canonical) validates
node --experimental-strip-types worker/scripts/dump-profiles.ts \
  | python3 scripts/cohort-harness/validate.py
```

`validate.py` reads a **JSON array of profiles** (the shape of
`listProfiles()`, `system_prompt` included) from a path or stdin, applies the
guardrails in `rules.yaml`, and prints a human table or `--json`.

```
validate.py [PATH] [--rules rules.yaml] [--json]
  PATH        JSON profile array; omit or use '-' to read stdin
  --rules     alternate rules file (default: sibling rules.yaml)
  --json      machine-readable output
```

Exit code:

| code | meaning |
|---|---|
| `0` | no FAIL findings (WARN findings still pass) |
| `1` | one or more FAIL findings |
| `2` | usage / input error (bad JSON, unreadable rules, wrong shape) |

`FAIL` blocks; `WARN` is advisory and passes. Flip any check's strictness in
`rules.yaml` under `severity:` — no Python edit needed.

## Guardrails (in `rules.yaml`)

- **Assets** — `assets_focus` is a non-empty, duplicate-free subset of the 7 AI
  Native Assets enum (`taste`, `intent_clarity`, `context_design`,
  `verification_reflex`, `delegation_judgment`, `iteration_reflex`, `ownership`).
- **Session** — `series_index ∈ [1, series_total]`; `hours > 0`; `id` unique
  across the array; every profile sharing a `cohort_id` agrees on `series_total`.
- **UX** — `welcome.example_prompts` non-empty (WARN); `suggestions.initial`
  has ≥1 `good` chip; a `weak` chip needs a `caption` (WARN); `naming_mode ≠
  fixed` requires a non-empty `naming_prompt_md`.
- **prompt ↔ profile** — `publishing.enabled=false` while the `system_prompt`
  promises publishing → FAIL (keyword phrases, with deferral/negation
  exemption); `enabled=true` must not pair with `strategy: local_only`;
  `system_prompt` non-empty and within the 2000–5000 char band (length is WARN).
- **Child cohorts** (`audience.age_range` max ≤ 12) —
  `analytics.log_user_messages` must be `false` (**HARD FAIL**);
  `strategy: per_user_github_pages` requires the consent flag named in
  `rules.yaml` (else FAIL; with the flag → WARN); the `system_prompt` must
  contain the exact phrase `외부 URL 호출 금지`.

## Consumer integration (studio)

The validator never imports studio code — it only reads JSON. Studio provides
the JSON via a tiny dump script and wires the pipe into npm + CI:

1. `worker/scripts/dump-profiles.ts` — `listProfiles()` → JSON on stdout
   (including each `system_prompt`).
2. `worker/package.json`:
   ```json
   "validate-profiles": "node --experimental-strip-types scripts/dump-profiles.ts | python3 scripts/cohort-harness/validate.py"
   ```
3. `.github/workflows/pr-ci.yml` — a `validate-profiles` job (needs `python3` +
   `npm ci`) next to `worker-typecheck`.

Because the engine is vendored, studio's CI runs the **same** rules every other
product would. To change a guardrail, edit `rules.yaml` **here** and re-run
`scripts/sync.sh` — never edit the vendored copy in a consumer.

## Vendoring

Canonical source: `hypeproof-harness/scripts/cohort-harness/`
Vendored to: `<consumer>/scripts/cohort-harness/` (rsync via `sync.sh`;
`SCRIPTS=(... cohort-harness)`).

Sediment and hypeprooflab have no cohort concept — they receive an inert copy,
exactly as they do for `docs-harness`. Harmless; keeps one canonical engine.

Drift detection: `sync.sh --check` exits 1 if any consumer's vendored copy
diverges. Provenance: each consumer gets `scripts/cohort-harness/HARNESS_VERSION`
with the harness HEAD SHA at sync time.

## Tested with

- Python 3.8+ (standard library only — `argparse`, `json`, `re`, `pathlib`).

Harness-side fixtures + assertions live in `tests/fixtures/cohort/` and
`tests/cohort-harness.sh` (also run as **T-V12** inside `tests/run.sh`):
`pass.json` (clean → exit 0), `warn.json` (WARN-only → exit 0), `fail.json`
(violations → exit 1), `malformed.json` (bad JSON → exit 2).
