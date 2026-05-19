---
name: hype-open-pr
description: Open a pull request for the current HypeProof Studio fix/feat branch — pushes the branch, creates the PR from the template, and fills Closes #N / Essence / Tested with the contributor. Use when a code change is ready to land and a contributor wants to open the PR (the PR-side counterpart of /report-ui).
user_invocable: true
triggers:
  - "open pr"
  - "open-pr"
  - "hype-open-pr"
  - "make a pr"
  - "create pull request"
  - "PR 만들어"
  - "PR 올려"
argument_hint: "[issue number, optional — inferred from branch if omitted]"
---

# hype-open-pr

Turn a finished fix/feat branch into a structured PR against `main`, the
PR-side counterpart of `/report-ui`. Wraps the deterministic harness
`scripts/open-pr.sh` and adds the part a bare script can't: filling the PR
body *with* the contributor.

Repo: `jayleekr/hypeproof-studio`. Policy: **PR-first, review optional**;
direct `main` push is maintainer-only (DEV-GUIDE §6).

## Preconditions

- On a `fix/*` or `feat/*` branch, not `main` (`git rev-parse --abbrev-ref HEAD`).
- Work is committed (no dirty tree). If dirty, help the contributor commit
  first — do not stash silently.
- `gh` authenticated (`gh auth status`). If not: `gh auth login` (repo scope).

## Flow

### 1. Resolve the issue number
From the argument, else parse the branch name (`fix/issue-<N>-<slug>` /
`feat/issue-<N>-<slug>`). If none found, ask the contributor for the issue #
(every code change should trace to an issue — file one with `/report-ui`
first if it doesn't exist).

### 2. Confirm the change is committed
`git status --porcelain` must be empty. If not, summarise the diff and help
write a commit (English message, no secrets) before continuing.

### 3. Open the PR
```
bash scripts/open-pr.sh
```
This refuses on `main`, pushes the branch (the pre-push hook allows non-main),
and runs `gh pr create --fill --base main` so `.github/pull_request_template.md`
is applied. Capture the printed PR URL. If it reports an existing PR, reuse it
(`gh pr view --json url -q .url`).

### 4. Fill the PR body with the contributor
The template has placeholders. Gather, in the contributor's language:
- **Closes #N** — set the resolved issue number (required; the merge
  auto-closes it).
- **What & why** — one tight paragraph.
- **Area** — keep the matching line(s) (worker / extension / docs·scripts /
  build·submodule).
- **Essence(s)** — for chat-panel changes, cite the §4.5 essence number(s)
  from METAPLAN. Challenge "serves none" for a chat-panel change.
- **Tested** — check the `Run & test` layer(s) actually run (DEV-GUIDE §4).
- **Checklist** — confirm branched off main, no secrets in diff, submodule
  pin untouched (unless this PR is an intentional bump).

Write the assembled body to a temp file and apply:
`gh pr edit <url> --body-file <tmp>`. Then `rm` the temp file.

### 5. Confirm
Show the PR URL. Remind: review is optional, merge when green; the
`main-guard` CI passes because this reached `main` via a PR. Delete the branch
after merge.

## Guardrails

- Never push to `main` or bypass the guard from this skill. It only opens PRs
  from feature branches.
- Never put secrets in the PR body/commits (`worker/.dev.vars` stays local).
  `scripts/collect-studio-env.sh` is the only sanctioned env dump and is
  secret-free.
- One PR per invocation. Don't merge automatically — opening ≠ merging.
- Don't touch the `vscodium-base` submodule pointer unless the contributor
  explicitly says this PR is a deliberate bump
  (`.claude/rules/build-pipeline.md`).
- English in the PR title/body (repo convention); converse in any language.
