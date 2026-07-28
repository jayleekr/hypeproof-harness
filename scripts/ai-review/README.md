# ai-review — the automation arm of hype-review

`review_pr.py` runs the hype-review criteria on a PR with Claude and **submits
the review**. It reuses the lenses and path→risk rules from
`scripts/hype-review/review.py` (one source of truth), so the bot and a human
apply the same judgement.

## Verdict contract (fail-safe)

- **APPROVE** only when the model returns `approve` *and* reports zero blockers.
- Any blocker (security / data / deploy / user-facing) → **REQUEST_CHANGES**
  (an approve-with-blockers verdict is downgraded automatically).
- A failed model call → **COMMENT**, never a fake approval.
- It refuses to review its own authored PR (reviewer ≠ author).

## Run

```bash
ANTHROPIC_API_KEY=… python3 scripts/ai-review/review_pr.py \
  --repo jayleekr/hypeproof-harness --pr 123 [--dry-run]
```

`--dry-run` prints the verdict and submits nothing.

## In CI

`.github/workflows/ai-review.yml` runs it on every PR. Provision:

- `ANTHROPIC_API_KEY` — without it the job posts a "not provisioned" comment and
  exits 0 (never blocks a PR).
- `HYPEPROOF_REVIEWER_TOKEN` — a **non-author** identity (reviewer bot / GitHub
  App with `pull-requests:write`) so the APPROVE counts toward branch
  protection. Absent → falls back to `GITHUB_TOKEN` (github-actions[bot]).

Making the bot's approval load-bearing (raising `required_approving_review_count`)
is a separate, deliberate policy change in `policy/profiles/*.yaml`.

## 상태

- 유닛 12건 통과 · 실 PR e2e 검증 완료.
- 활성: `ANTHROPIC_API_KEY` 프로비저닝됨. 승인 카운트 신원(GitHub App)은 후속.
