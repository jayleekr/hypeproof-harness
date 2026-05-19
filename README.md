# hypeproof-harness

Shared collaboration harness for the HypeProof repos. Consumed as a git
submodule (`.harness`) by `hypeproof-studio`, `sediment`, and `hypeprooflab`.

> Provenance: extracted from `jayleekr/hypeproof-studio` @ `3e85278` on
> 2026-05-19. **Scope corrected the same day** after a portability test
> (T6) — see "What changed and why" below.

## What is shared (lives here)

| Path | Purpose |
|---|---|
| `skills/skill-creator/` | vendored generic skill-authoring toolkit — zero repo coupling (verified) |
| `github/ISSUE_TEMPLATE/` | canonical issue templates (bug / feature / ux / config) |
| `github/pull_request_template.md` | canonical PR template |
| `LABELS.md` | `human-needed` label policy (owner: 지용, due 5/21) |

`.github/*` is **canonical-source-only**: GitHub does not follow submodule
symlinks, so a consumer repo that wants templates copies them in as real
files. Skills are consumed by symlink into that repo's `.claude/skills/`.

## What is NOT shared

`hype-open-pr` and `report-ui` were initially extracted here but **moved
back to `hypeproof-studio` as studio-local skills**. A portability test
(T6, 2026-05-19) proved they are not repo-agnostic: hardcoded
`REPO_SLUG="jayleekr/hypeproof-studio"` in `file-issue.sh`, hard
dependency on repo-level `scripts/open-pr.sh` / `scripts/collect-studio-env.sh`,
and references to studio-only concepts (METAPLAN §4.5, `main-guard`,
`vscodium-base`, `e2e/`, the built `.app`). A repo-string swap would be
cosmetic; the coupling is structural. They stay studio-local.

Also not shared (studio-local): `.claude/rules/{branding-swap,build-pipeline,
extension-dev}.md`, `.github/workflows/*`, `e2e/`, `vscodium-base`.

## How a repo consumes this

```bash
git submodule add git@github.com:jayleekr/hypeproof-harness.git .harness
ln -s ../../.harness/skills/skill-creator .claude/skills/skill-creator
```

Pin the submodule pointer deliberately; never auto-follow.

## What changed and why

- v1 (`386de0d`): over-included `hype-open-pr` + `report-ui`.
- v2 (this commit): scope corrected to genuinely-shared only, after T6
  showed the two PR/issue skills are structurally studio-bound. Honest
  scope beats a fake-generic shim wired into three repos.

Topology + OVERRIDE runbook + full test report:
`jay/reports/2026-05-19-repo-structure-diagram.html` (hypeprooflab).
