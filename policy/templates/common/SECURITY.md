# Security Policy

## Reporting

Do not open a public issue for secrets, auth bypasses, token leaks, or deploy
credential problems.

Send the report directly to the maintainers:

- GitHub: `@jayleekr`
- GitHub: `@JeHyeong2`

Include the affected repo, branch or commit, reproduction steps, and whether any
credential may have been exposed. Never include full secret values in the report.

## Secret Handling

- Do not commit `.env`, private keys, tokens, Fly/Vercel/Cloudflare credentials,
  or webhook URLs.
- If a secret reaches git, rotate it first, then remove it from history if the
  exposure warrants it.
- GitHub Secrets, Fly secrets, Vercel env vars, and Cloudflare secrets are the
  only approved storage locations for production credentials.

## Branch Policy

All production-affecting changes should enter `main` through PR review and CI.
Public repos may accept external PRs, but only HypeProof members or approved
automation may merge or deploy.
