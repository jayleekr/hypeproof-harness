# M005 — Identity Isolation Cutover Runbook (Phase 2 / 3 / 4)

Status: **package for human execution.** No account, credential, or system
change has been made by producing this document. Every privileged step below is
run by a human; the scripts under `scripts/identity-isolation/` only emit and
verify. No secret values appear anywhere in this package.

## 0. Why (root cause, measured 2026-07-22)

The autonomous runtime runs as OS user `jaylee` (uid 501). Even after M004
narrowed the GitHub token, that is reversible: a session running as `jaylee` can
read `~/.ssh/id_ed25519` (passphrase-less), the login keychain, and `gh` auth,
and re-acquire Jay's owner rights. **Narrowing the token is necessary but not
sufficient while uid is shared.** M005 splits the OS identity so the delegated
automation credential is the *only* credential the runtime can reach.

Target end state:

```
jaylee           = human administrator workspace (untouched)
hypeproof-agent  = autonomous runtime, separate OS user (uid auto-assigned)
autonomous agent = uses ONLY the delegated automation credential; inherits no
                   Jay ssh key / keychain / gh auth / cloud admin / dotfiles
```

Measured baseline (from `phase3-00-preflight.sh`, read-only):

| Fact | Value |
|---|---|
| Runtime OS user | `jaylee` (uid 501) |
| GitHub identity used by automation | `jayleekr` (id 25076199), OAuth `gho_…` |
| Token scopes (over-scoped) | `admin:public_key, delete_repo, gist, read:org, repo` |
| Git transport | harness/studio/sediment = **ssh**; hypeprooflab = **https** |
| SSH key | `~/.ssh/id_ed25519`, **passphrase-less**, 0600 |
| Claude token | `~/.config/cron/env` (0600), sourced by `cron-prompts/cron-env.sh` |
| `~/.gitconfig` | **0644 (world-readable)** — tightened in Step 20 |
| Autonomous jobs | `~/Library/LaunchAgents/com.hypeproof.cron.*.plist` (12 real jobs) |

---

## 1. Phase 2 — automation GitHub identity (decision + procedure)

**Decision: dedicated machine user (`hypeproof-automation`) + fine-grained PAT.**
This confirms M004 WS1. Re-evaluated against GitHub App and classic PAT:

| Option | Fine-grained permission model | Cron/launchd compatibility | Verdict |
|---|---|---|---|
| **Fine-grained PAT on machine user** | Exact repo list + per-permission toggles (`Administration: read`, `Workflows: none`) | **Static secret** — drops into the existing 0600 env-file model with zero new code | **Chosen** |
| GitHub App (installation token) | Same permission granularity | Needs a per-run JWT→installation-token mint step (1 h expiry) inside `run-job.sh`; app private key is still a static secret at rest | Rejected — more moving parts, same at-rest exposure *(inference: App token lifecycle not measured here)* |
| Classic PAT on machine user | Coarse scopes only (`repo` implies admin-ish on repos you can admin) | Static secret | Rejected — cannot express `Administration: none/read` |

**Deciding constraint (measured):** the launchd jobs already read a static token
from a 0600 env file (`~/.config/cron/env`, `set -a`). A static PAT fits that
exact shape. A GitHub App would add a token-minting dependency without removing
the at-rest secret. *(GitHub App 1 h token-expiry behavior is documented by
GitHub, not measured in this environment — marked inference.)*

**Naming (do not conflate):** GitHub login `hypeproof-automation` (already in
`policy/automation-identity.yaml` and `policy/control-plane.yaml`); OS account
`hypeproof-agent` (this milestone). Two different identities.

The exact grants live in **`policy/automation-identity.yaml`** (an M004
control-plane artifact). Its M005 validation + freshening to v2 (re-measured
transports/perms, the concrete `uid_isolation_m005` block, and the
non-inheritance contract) rides with the M004 branch / PR #67, since this file
does not exist on `main` yet — it cannot be edited from a `main`-based PR.
Human-run procedure (GitHub UI, no script issues tokens):

1. Create machine user `hypeproof-automation` (new account, separate email).
2. Add it as collaborator with **write** (not admin) on `jayleekr/hypeprooflab`:
   `gh api -X PUT repos/jayleekr/hypeprooflab/collaborators/hypeproof-automation -f permission=push`
3. As `hypeproof-automation`, create a **fine-grained PAT**:
   - Resource owner: `hypeproof-automation`
   - Repos: `hypeprooflab` (write); `hypeproof-harness`, `hypeproof-studio`, `sediment` (read)
   - Grant: `Metadata:read`, `Contents:write`, `Pull requests:write`,
     `Issues:write`, `Administration:read`, `Actions:read`, `Checks:read`
   - **Withhold:** `Administration:write`, `Secrets`, `Environments`,
     `Workflows`, `Actions:write` (default)
4. Two deny-checks that MUST fail for the new token (side-effect-free):
   - `gh api -X PUT repos/jayleekr/hypeprooflab/branches/main/protection …` → **403** (Administration read-only)
   - `gh api -X PUT repos/jayleekr/hypeprooflab/contents/.github/workflows/x.yml …` → **404** (no Workflows scope)

Findings A6/A7 (why `Administration:read` only, and why HTTPS+PAT not an SSH
deploy key) are documented in `policy/automation-identity.yaml`.

---

## 2. Phase 3 — macOS uid isolation (ordered human procedure)

Each step: run the script in `--dry-run` first, read the plan, then run the
emitted commands yourself. `--apply` is refused by design.

| # | Step | Script | Privilege |
|---|---|---|---|
| 00 | Preflight (read-only baseline) | `phase3-00-preflight.sh` | none — run now |
| 10 | Create `hypeproof-agent` (non-admin, hidden, own home) | `phase3-10-create-account.sh` | sudo (human) |
| 20 | Harden Jay's cred stores + define agent-owned tree | `phase3-20-filesystem-ownership.sh` | jaylee + sudo |
| 30 | Clone runtime repos into agent home over HTTPS | `phase3-30-checkout-repos.sh` | sudo -u agent |
| 40 | Provision fine-grained PAT + Claude token in agent home | `phase3-40-provision-credentials.sh` | human (no values) |
| 50 | Migrate `com.hypeproof.cron.*` to agent **LaunchDaemons** | `phase3-50-migrate-launchd.sh` | sudo (human) |
| 60 | Minimal agent env + assertions | `phase3-60-agent-env.sh` | sudo -u agent |
| 90 | Rollback (reverse 50→10) | `phase3-90-rollback.sh` | sudo (human) |

### Step dependencies

```
00 (baseline)
    └─ Phase 2 (machine user + PAT)         ← must exist before 30/40
        └─ 10 (account)
            └─ 20 (ownership)               ← agent home must exist (10)
                └─ 40 (credentials)         ← agent home + PAT (Phase 2)
                    └─ 30 (checkouts)       ← needs the PAT store from 40
                        └─ 60 (env)         ← needs checkouts (30)
                            └─ 50 (launchd) ← last; points daemons at 30's checkouts
                                └─ Phase 4 (certify) → then retire Jay fallback
```

### Key macOS constraints (design notes)

- **LaunchAgent vs LaunchDaemon (HIGH confidence).** A user *LaunchAgent* only
  runs inside that user's GUI (aqua) login session. A hidden, non-interactive
  service account is never "logged in", so its LaunchAgents would not fire
  reliably. Step 50 therefore generates **LaunchDaemons** in
  `/Library/LaunchDaemons` with `<UserName>hypeproof-agent</UserName>` — these
  run at boot regardless of login and drop privilege to the agent uid. The
  fragile LaunchAgent + `launchctl bootstrap gui/<uid>` alternative is not used.
- **Keychain isolation is free from the uid split (HIGH confidence).** Jay's
  `~/Library/Keychains/*.keychain-db` is per-uid and locked; a different uid
  cannot use it. No extra step; verified in Phase 4 (A2).
- **`sysadminctl` auto-assigns the UID.** Do not hardcode one (501–503 are in
  use). The account is referenced by name everywhere.

---

## 3. Phase 4 — non-inheritance verification suite

Run **as the agent** after Phase 3:
`su - hypeproof-agent -c '.../phase4-noninheritance-suite.sh'`
Exit non-zero on any failed assertion. Every MUST-FAIL probe is side-effect-free
(nonexistent target or value-preserving no-op).

### MUST FAIL from the agent identity (expected server/OS response)

| ID | Attempt | Expected result |
|---|---|---|
| A1 | Read `~jaylee/.ssh/id_ed25519` | OS **EACCES** (permission denied) |
| A2 | Use Jay's login-keychain github cred | Item not found (per-uid keychain) |
| A3 | `gh` identity resolve | **not** `jayleekr` (machine user / unauth) |
| A4 | Repo administration write (no-op PATCH) | HTTP **403** |
| A5 | Branch-protection mutation (nonexistent branch) | HTTP **403** (404 only if authz'd) |
| A6 | Repo deletion (nonexistent repo) | HTTP **403/404** |
| A7 | SSH-key admin (`GET user/keys`) | HTTP **403/404** |

### MUST SUCCEED from the agent identity

| ID | Attempt | Expected result | Reference run (as jaylee) |
|---|---|---|---|
| B1 | Clone/ls-remote authorized repo | success | **PASS** (verified 2026-07-22) |
| B2 | `permissions.push` on write target | `true` | **PASS** |
| B3 | Read branch protection (observe-only) | HTTP **200** | **PASS** |
| B4 | Read CI status/checks | HTTP **200** | **PASS** |
| B5 | Feature branch create+push+delete | success | opt-in `--write-probe`, agent-only |

The suite runs in **reference mode** as `jaylee` today: the B rows pass (proving
the "should-succeed" targets are reachable) and the A rows are reported N/A
(Jay legitimately holds those rights — only meaningful from the agent).

---

## 4. Rollback

`phase3-90-rollback.sh` emits the reverse of every step in reverse order
(50→10): bootout the agent daemons, restore Jay's jobs from
`~/Library/LaunchAgents/.migrated-to-agent/`, drop the agent runtime and
credential files, restore `~/.gitconfig` to 0644, and finally
`sysadminctl -deleteUser`. Full rollback returns to the pre-M005 state
(automation as `jaylee`, accepting the original risk). Keep it available until
Phase 4 passes; **do not delete the old Jay-domain plists** (rename only) until
then.

## 5. Constraints honored

- No `sudo`, user creation, or credential issuance/rotation was executed —
  scripts emit only; the human runs the privileged lines.
- No secret values printed (names, paths, scopes only).
- Work isolated in a new git worktree/branch; **no `git stash`** used.
- Out-of-scope paths untouched: `work/**`, `personal finance/**`, `life/**`,
  `journal/**`, `inbox/**`, `agon/**`.

## 6. Known limitations

- Reference-mode Phase 4 proves the "should-succeed" targets are **reachable**,
  not that the machine-user PAT specifically yields 200 on B3/B4 — that requires
  running as the agent with the PAT (deferred until the account exists).
- GitHub App token-lifecycle claims in §1 are from GitHub's documentation, not
  measured in this environment (inference, flagged).
- `sysadminctl`/`dscl`/`launchctl bootstrap system` semantics are stable on
  macOS 15.7 (this host) but are not exercised by this package — the emitted
  commands are for human execution and should be validated on first run in a
  reversible window (rollback ready).
