# Security Policy

## Reporting

Do not open a public issue for secrets, token leaks, policy bypasses, or
automation that could mutate HypeProof repos unexpectedly.

Send the report directly to the maintainers:

- GitHub: `@jayleekr`
- GitHub: `@JeHyeong2`

Include the affected policy file, script, branch or commit, reproduction steps,
and whether any credential may have been exposed. Never include full secret
values.

## Secret Handling

`hypeproof-harness` stores policy and secret names, never secret values.

- Do not commit GitHub tokens, Fly/Vercel/Cloudflare credentials, webhook URLs,
  or private keys.
- Repo governance scripts may check that required secrets exist, but must not
  print values.
- If a secret reaches git, rotate it first, then decide whether history cleanup
  is needed.

## Branch Policy

This repo is the governance source of truth. Changes to shared skills, member
guides, repo policy, audit/apply/create tooling, and templates should enter
`main` through PR review and CI.
