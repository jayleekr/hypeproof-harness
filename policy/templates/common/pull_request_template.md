<!--
HypeProof PR policy:
- Link the issue with Closes/Fixes/Resolves #...
- Keep main protected: no direct push.
- Request all active HypeProof members as reviewers, excluding the PR author where GitHub disallows it.
- Never include secret values in screenshots, logs, or code.
-->

## What & why

<!-- What changed, and the problem it solves. -->

## Tested

<!-- Commands or manual checks run. -->

## Security / governance

- [ ] No secrets or credentials in the diff
- [ ] All active HypeProof members were requested as reviewers, excluding the PR author where GitHub disallows it
- [ ] No new public unauthenticated surface without rate limit / abuse notes
- [ ] No workflow grants write/deploy permissions to external PR or comment triggers
- [ ] Production deploy authority remains declared in policy; no hidden provider auto-deploy path was added
- [ ] Branch protection / required checks remain compatible with this change

Closes #
