# Solver contract — how a downstream skill consumes these issues

Every issue filed by `/report-ui` is **solver-ready**: structured so a future
issue-solving skill (e.g. `/orbit` ops flavor, or the `issue-explorer` /
`issue-fixer` agents) can pick it up without a human re-triaging it.

## Discovery

```bash
gh issue list --repo jayleekr/hypeproof-studio \
  --label solver:ready --state open --json number,title,labels
```

Filter by work type via the `type:feature` / `type:ux` / `type:bug` label.
`source:studio-ui` means it carries a verified environment snapshot.

## Parseable blocks in the issue body

| Marker | Content | Use |
|---|---|---|
| `<!-- HPS-ENV-START -->` … `<!-- HPS-ENV-END -->` | A fenced ```json``` block, schema `hps-env/1` | The env at report time. Re-run `scripts/collect-studio-env.sh` and diff to detect drift before attempting a fix. |
| `<!-- HPS-SOLVER: type=…; slug=…; source=studio-ui -->` | Routing metadata | `type` selects the fix strategy; `slug` maps to `evidence/<slug>.png` on the `contrib-evidence` branch. |

Parse env JSON:

```bash
gh issue view <N> --repo jayleekr/hypeproof-studio --json body -q .body \
  | sed -n '/HPS-ENV-START/,/HPS-ENV-END/p' \
  | sed -n '/```json/,/```/p' | sed '1d;$d'
```

## Evidence

Screenshot lives at `evidence/<slug>.png` on the orphan `contrib-evidence`
branch (never on `main`). Raw URL:
`https://github.com/jayleekr/hypeproof-studio/blob/contrib-evidence/evidence/<slug>.png?raw=true`

## Solver handshake (suggested)

1. On pickup: comment + add `solver:in-progress`, remove `solver:ready`.
2. Open a branch `fix/issue-<N>-<slug>`; reference the issue in the PR.
3. On merge: GitHub auto-closes via `Closes #<N>` in the PR body.
4. If env drift is detected (collector output differs materially from the
   embedded snapshot), comment the diff and re-label `needs-repro` instead of
   guessing.
