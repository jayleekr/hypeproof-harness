# hypeproof-harness

Shared **skill** harness for the HypeProof repos. Consumed as a git
submodule (`.harness`) by `hypeproof-studio`, `sediment`, and
`hypeprooflab`; each repo symlinks the shared skill(s) into its
`.claude/skills/`.

> Provenance: extracted from `jayleekr/hypeproof-studio` @ `3e85278` on
> 2026-05-19. Scope corrected twice the same day (see history below).

## What is shared (lives here)

| Path | Purpose |
|---|---|
| `skills/skill-creator/` | vendored generic skill-authoring toolkit — zero repo coupling (verified, T6) |

That is the whole harness. It is a **skill** harness; only genuinely
repo-agnostic, symlink-consumable skills belong here.

## Consume

```bash
git submodule add git@github.com:jayleekr/hypeproof-harness.git .harness
ln -s ../../.harness/skills/skill-creator .claude/skills/skill-creator
```

Pin the submodule deliberately; never auto-follow.

## What is NOT shared (and why)

- **`hype-open-pr`, `report-ui`** — structurally studio-bound (hardcoded
  `REPO_SLUG`, repo-level `scripts/*` deps, METAPLAN/main-guard/vscodium
  refs). Studio-local. (T6, 2026-05-19.)
- **`.github` issue/PR templates** — not a skill; GitHub does not follow
  submodule symlinks so they are not submodule-consumable; and the
  templates are studio-flow-specific. Studio-local. A repo that wants
  templates authors its own.
- **`LABELS.md` (human-needed policy)** — a policy doc, not a skill;
  owned by 지용 (due 5/21). Lives with whoever owns the policy, not in
  the skill harness.
- Studio-local also: `.claude/rules/*`, `.github/workflows/*`, `e2e/`,
  `vscodium-base`.

## History

- `386de0d` v1 — over-included `hype-open-pr` + `report-ui`.
- `df6fda2` v2 — dropped those two after portability test T6; still
  carried `.github` + `LABELS`.
- this commit v3 — dropped `.github` + `LABELS` too: a skill harness
  shares skills, nothing else. Honest scope over convenient bundling.

Topology + runbook + full test report:
`jay/reports/2026-05-19-repo-structure-diagram.html` (hypeprooflab).
