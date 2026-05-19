<!--
Filed via the issue → PR flow in CONTRIBUTING.md.
Branch name should be fix/issue-<N>-<slug> or feat/issue-<N>-<slug>.
-->

Closes #<!-- issue number — required so the merge auto-closes it -->

## What & why

<!-- What changed, and the problem it solves. Keep it concrete. -->

## Area

<!-- delete the ones that don't apply -->
- worker (`worker/`)
- extension (`extensions/hypeproof-chat/`)
- docs / scripts
- build / `vscodium-base` submodule (bump policy: .claude/rules/build-pipeline.md)

## Essence(s) served

<!-- Required for chat-panel changes. Cite the §4.5 essence number(s) from
     METAPLAN. If a chat-panel change serves none, it is probably noise. -->

## Tested

<!-- Which "Run & test" layer(s) you ran (CONTRIBUTING.md). -->
- [ ] `cd worker && npm test && npm run typecheck`
- [ ] `cd e2e && npm test` (built .app + dev-stack running)
- [ ] manual: <!-- what you clicked through -->

## Checklist

- [ ] Branched off `main` (no direct push to `main`)
- [ ] No secrets in the diff (`worker/.dev.vars` stays local)
- [ ] Submodule pointer untouched unless this PR is intentionally a bump
