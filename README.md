# hypeproof-harness

Shared collaboration harness for the HypeProof repos. Consumed as a git
submodule by `hypeproof-studio`, `sediment`, and `hypeprooflab` so the
issue-driven dev workflow is one source of truth, not three drifting copies.

> Provenance: extracted from `jayleekr/hypeproof-studio` @ `3e85278`
> on 2026-05-19. Studio was the only repo that had these; lab/sediment
> have their own (different) issue tooling — see "Open risk" below.

## What is shared (lives here)

| Path | Purpose |
|---|---|
| `skills/hype-open-pr/` | PR creation as a skill |
| `skills/report-ui/` | feature / UX / bug issue filing skill (+ capture scripts) |
| `skills/skill-creator/` | vendored generic skill-authoring toolkit |
| `github/ISSUE_TEMPLATE/` | bug / feature / ux_suggestion / config |
| `github/pull_request_template.md` | shared PR template |
| `LABELS.md` | `human-needed` label policy (owner: 지용, due 5/21) |

## What is NOT shared (stays studio-local — do not pull in)

- `.claude/rules/{branding-swap,build-pipeline,extension-dev}.md` — VSCodium-build specific
- `.github/workflows/{build-windows,release,upstream-sync,main-guard}.yml` — studio release pipeline
- `e2e/` — studio Playwright/Electron flows
- `vscodium-base` — studio submodule

## How a repo consumes this

```bash
git submodule add git@github.com:jayleekr/hypeproof-harness.git .harness
# surface skills/templates per that repo's convention (symlink or settings)
```

Pin the submodule pointer deliberately; never auto-follow.

## Open risk (must verify before wiring into lab/sediment)

`hype-open-pr` / `report-ui` were authored against studio's GitHub repo +
its `.github` templates. Cross-repo portability is **unverified**. Sequence:
extract → wire studio first → smoke test → only then wire sediment/lab
(lab also has its own `issue-filer`/`issue-ops`/`curator` skills that may
collide). See the OVERRIDE runbook in
`jay/reports/2026-05-19-repo-structure-diagram.html`.
