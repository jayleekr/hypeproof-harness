---
name: hypeproof-operator
description: "Use this skill for HypeProof-only repository operations: governance policy, member permissions, branch protection, security incidents, docs consistency, Vercel/GitHub deploy checks, review requests, PR monitoring, merge sequencing, and release repo handling for hypeproof-harness, hypeproof-studio, hypeprooflab, sediment, and their release repos. This skill must scope actions to HypeProof-managed projects only and must not operate on personal blogs, side projects, or unrelated repos unless the user explicitly gives a separate repo-specific override."
metadata:
  short-description: "HypeProof-only repo governance, security, review, merge, and deploy operations"
---

# HypeProof Operator

This skill keeps Codex focused on HypeProof work only. Treat it as the operating runbook for requests like "all repos", "review everything", "merge when approved", "fix docs", "check deploy", "branch protection", "security issue", or "member permissions" when the conversation is about HypeProof.

## Scope Gate

Before reading, mutating, reviewing, or merging anything, resolve the repo scope.

Allowed HypeProof scope:

- `jayleekr/hypeproof-harness`
- `jayleekr/hypeproof-studio`
- `jayleekr/hypeprooflab`
- `jayleekr/sediment`
- `jayleekr/hypeproof-studio-releases`
- `jayleekr/sediment-cli-releases`
- Any future repo already listed in `hypeproof-harness/policy/repos.yaml` whose `products` or `lifecycle` clearly belong to HypeProof product, governance, or release operations.

Excluded by default:

- Personal blog/site repos such as `jayleekr/jayleekr.github.io`.
- Side projects, experiments, archives, or unrelated repos even if they are under the same GitHub account.
- Repos not present in `policy/repos.yaml`, unless the user explicitly asks to onboard that repo into HypeProof governance first.

If the user says "all repos", interpret it as "all allowed HypeProof scope", not all repositories accessible to the GitHub token.

## Control Plane

Use `jayleekr/hypeproof-harness` as the source of truth.

- Repository list and desired settings: `policy/repos.yaml`
- Members and permissions: `policy/members.yaml`
- Policy profiles: `policy/profiles/*.yaml`
- Shared agent guidance: `docs/AGENT-GUIDE.ko.md`
- Shared skills: `skills/`

Never patch vendored copies inside consumer repos when the canonical file lives in harness. Patch harness, then sync or open downstream PRs as needed.

## Default Workflow

1. Scope: identify the exact HypeProof repo set and reject accidental personal/side repos.
2. Inspect: read policy, current PRs/issues, CI, deploy state, and local dirty worktrees before mutating.
3. Track: create or update a GitHub issue for governance/security/docs/deploy work unless the task is a tiny read-only check.
4. Branch: use `fix/`, `feat/`, `docs/`, or `chore/`; avoid direct `main` pushes.
5. Change: keep edits narrow and aligned with the target repo.
6. Validate: run the smallest meaningful local tests plus repo-specific checks.
7. PR: include `Closes #...` or a clear issue link, request all HypeProof reviewers, and explain risk.
8. Monitor: watch CI, reviews, branch protection, deploys, and merge status until the work is merged or blocked by an external condition.

## Governance Tasks

For branch protection, visibility, collaborator, Actions, secret scanning, or repo settings:

```bash
python3 scripts/repo-governance/audit.py --offline
python3 scripts/repo-governance/audit.py --all
python3 scripts/repo-governance/apply.py --repo owner/name --module repo_settings --apply
python3 scripts/repo-governance/apply.py --repo owner/name --module collaborators --apply
python3 scripts/repo-governance/apply.py --repo owner/name --module branch_protection --apply
```

Use `--module` narrowly. If GitHub personal-account plan limits block branch protection or private repo controls, record it in an issue instead of pretending it is fixed.

Public-by-default operating stance:

- Public repos are acceptable for HypeProof product/governance work.
- Code contribution should still be restricted by collaborator permissions and branch protection.
- Pending collaborator invitations are not fixed until the invitee accepts; track them as external blockers.

## Review Requests

When requesting reviews for HypeProof PRs, request every active member unless the user explicitly narrows the audience.

Use `policy/members.yaml` as the source of members. Treat authors as still useful for awareness, but remember branch protection needs a non-author approval.

If a `hype-review` harness exists, prefer it. Otherwise use GitHub directly:

```bash
gh pr edit <number> --repo owner/name --add-reviewer user1 --add-reviewer user2
```

Review guidance should teach role-based thinking:

- Maintainer lens: policy, security, release safety, rollback.
- Product lens: docs, UX, deployment behavior, user-facing regressions.
- Contributor lens: implementation clarity, tests, maintainability.

When summarizing reviewer state, separate "requested", "approved", "changes requested", "pending invitation", and "author cannot satisfy required non-author approval".

## Merge And Auto-Merge

Do not direct-merge just because checks are green. Merge only when branch protection, review policy, and user intent are satisfied.

Safe auto-merge policy:

- Enable auto-merge only for HypeProof repos whose harness policy explicitly allows it.
- Never enable auto-merge for excluded repos such as personal blogs.
- Prefer auto-merge reservation over immediate merge when the only blockers are required reviews.
- Do not auto-merge release repos unless a release-specific policy explicitly permits it.

If `scripts/hype-merge/monitor.py` or `scripts/hype-merge/automerge.py` exists, use it. Otherwise inspect with:

```bash
gh pr list --repo owner/name --state open --json number,title,author,reviewDecision,mergeStateStatus,autoMergeRequest,statusCheckRollup
gh pr view <number> --repo owner/name --json reviews,reviewDecision,mergeStateStatus,statusCheckRollup,autoMergeRequest
```

Before enabling auto-merge, verify the head SHA and use `--match-head-commit` where possible.

## Security Incidents

For exposed secrets, OAuth client secrets, deployment tokens, or suspected credentials:

1. Do not repeat the secret in chat, issues, commit messages, or logs.
2. Create a security/governance issue in the relevant HypeProof repo or harness.
3. Rotate or revoke the credential in the provider console; this is external and must be marked blocked until done.
4. Remove the secret from current files and add scanning/prevention tests.
5. Verify public history exposure. If history purge is needed, track it separately and avoid destructive rewrites without explicit approval.
6. Keep private/public visibility decisions tied to the security issue until verification passes.

For Google OAuth exposure, rotation in Google Cloud Console is required; repo edits alone are not enough.

## Deploy And Vercel

When Vercel or deploy behavior is involved:

- Identify the deploy source: repo, branch, project, commit SHA, and actor.
- Confirm whether the deploy should happen on PR, merge to default branch, release tag, or manual workflow.
- If Vercel says a GitHub user is not a team member, distinguish between Vercel team membership, GitHub collaborator permission, and repo visibility.
- For public repos, Vercel can often deploy from GitHub without adding every contributor to a paid Vercel team; verify the actual integration.
- After merge, monitor the deployment URL until success or a concrete failure is found.

## Product Docs

For product docs consistency across `hypeproof-studio`, `hypeprooflab`, and `sediment`:

- Check both repo docs and live URLs when the user mentions broken links or deployed docs.
- Keep design and navigation consistent across products.
- Fix links directly and run a link/build check when available.
- Do not silently move product docs into personal or unrelated repos.

## Reporting

End with:

- What repo scope was used.
- What changed.
- What was verified.
- What remains blocked externally, such as approvals, pending invitations, provider console rotation, plan limits, or deploy propagation.

If you excluded a repo from scope, name it and explain that it is outside HypeProof-only operation.
