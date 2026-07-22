# M005 — Identity Isolation Cutover (Phase 2/3/4)

Human-run scripts that migrate the autonomous runtime off Jay's OS identity
(`jaylee`, uid 501) onto a dedicated, credential-isolated OS account
(`hypeproof-agent`). This closes the M005 Phase 0 root cause: *while the session
runs as uid `jaylee`, narrowing the GitHub token is reversible* — the session
can still read Jay's ssh key / keychain and re-acquire owner rights.

**Nothing here changes system state on its own.** Every privileged step is
EMITTED for a human to review and run. Scripts default to `--dry-run`; `--apply`
is deliberately refused. No secret values are ever printed.

See the full ordered runbook: `docs/M005-IDENTITY-ISOLATION.ko.md`.

## Files

| Script | What it does | Safe to run now? |
|---|---|---|
| `lib.sh` | Shared helpers, constants, `--dry-run`/`--emit` plumbing, apply-refusal | sourced only |
| `phase3-00-preflight.sh` | **Read-only** assessment of current state + drift check | **Yes (as jaylee)** |
| `phase3-10-create-account.sh` | Emit: create non-admin, hidden `hypeproof-agent` account | dry-run only |
| `phase3-20-filesystem-ownership.sh` | Emit: harden Jay's cred stores + define agent-owned tree | dry-run only |
| `phase3-30-checkout-repos.sh` | Emit: clone runtime repos into agent home over **HTTPS** | dry-run only |
| `phase3-40-provision-credentials.sh` | Emit: provision fine-grained PAT + Claude token in agent home | dry-run only |
| `phase3-50-migrate-launchd.sh` | Generate agent-context **LaunchDaemons**; emit install plan | generates files only |
| `phase3-60-agent-env.sh` | Emit: minimal agent env + assertions | dry-run only |
| `phase3-90-rollback.sh` | Emit: reverse every step (50→10) back to pre-M005 | dry-run only |
| `phase4-noninheritance-suite.sh` | **Verification suite** — MUST-FAIL / MUST-PASS probes | reference now; certify as agent |
| `examples/*.plist.example` | One committed sample of a transformed LaunchDaemon | reference |

## Modes

```
<script>.sh                 # --dry-run (default): print the plan, mutate nothing
<script>.sh --emit out.sh   # write reviewable 0700 command file; runs nothing
<script>.sh --apply         # REFUSED (exit 3) — privileged steps are human-only
```

## Run order (human)

1. `phase3-00-preflight.sh` — confirm baseline (safe now).
2. Phase 2 (GitHub UI, human): create machine user `hypeproof-automation` +
   fine-grained PAT per `policy/automation-identity.yaml`.
3. `phase3-10` → `phase3-60` — review each dry-run, then run the emitted commands.
4. `phase4-noninheritance-suite.sh` **as `hypeproof-agent`** — must exit 0.
5. Only after Phase 4 passes: retire the Jay-path fallback (`phase3-50` step 3).
   Keep `phase3-90-rollback.sh` on hand throughout.

## Non-inheritance contract verified in Phase 4

MUST FAIL as agent: read Jay ssh key · use Jay keychain github cred · gh as
jayleekr · repo admin write · branch-protection mutation · repo deletion · ssh
key admin.
MUST PASS as agent: clone authorized repo · feature branch create+push · read CI
status · read protection (observe-only) · comment on owned PR.
