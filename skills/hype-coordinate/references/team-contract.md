# HypeProof five-session operating contract

## Scope, language, and authority

Use this contract only for HypeProof work in jayleekr/hypeproof-harness,
jayleekr/hypeproof-studio, and jayleekr/hypeprooflab. Read MISSION.md →
CLAUDE.md → AGENTS.md and applicable repository skills. Harness remains
canonical for shared repository governance; these personal skills do not
replace it or grant new approval authority.

Work and write engineering handoffs in English. Report and ask the user
in Korean. Preserve existing document/UI language and bilingual rules.

A role invocation starts useful work without requiring a specific issue
number. It authorizes routine work within the established HypeProof task:
read current state, derive approved requirements, track issues, make scoped
changes, test, commit, push branches, create PRs, and integrate them under
repository rules. For Jay-hosted HypeProof delivery, Jay's standing instruction
authorizes A to merge ordinary product work without requesting or waiting for
peer review. It does not decide new business questions or bypass an enforced
technical gate.
Do not send unrelated external messages. Do not create more agents/sessions
unless separately authorized. Stay in one role unless explicitly reassigned.

## Discovery is broader than the current manifest

Locate the allowed repos through the current project/remotes and sibling
checkouts; never reset a dirty primary checkout. Fetch current remote refs.
Read current open issues, PRs, review/CI changes, and active claims. On first
start enumerate the current queue; later use a saved cursor with an overlap
window and deduplicate by repo + item + revision. Paginate reads. Failed or
partial reads mean unknown coverage, not an empty backlog.

Locate Studio's Product Intent, requirements/design/testing documents,
config/requirement-work.json, and scripts/next-work.py. Use the canonical
Harness reader, setting HYPEPROOF_HARNESS to its actual checkout if needed.
Run --check for integrity and the normal command/--json for current GitHub
availability. Missing tooling is a concrete setup task: inspect its current
implementation/adoption PR and use a separate discovery checkout when needed.
Do not wait for the user to provide a bootstrap PR number.

Inspect new/changed requirement documents and requirement-defining PRs even
when the manifest has not registered them. Integrity failure is a derivation
or synchronization task, not a reason to stop all discovery. Inspect actual
source and linked issues before deciding what remains unimplemented.

New requirement PRs are intake, not implementation completion. Preserve their
source revision and approval status, reuse existing epics/issues, and derive
missing execution packets. Do not duplicate a PR author's active work or treat
an unmerged proposal as approved main. Explicit existing user decisions remain
authorization; do not invent a new approval gate for already-decided work.

## Shared queue and acknowledgment

GitHub issues/PRs are the cross-product coordination record. Neither tool is
assumed able to see the other product's conversation or receive an undelivered packet.
Use the existing coordination tracker if available; the coordinator may create
one scoped tracker if absent after checking for duplicates.

Each assignment records:
- stable packet ID; source intent/requirements and revision
- parent issue/PR; unmet condition and next action
- proposed role; accepted session ID; branch/worktree
- allowed file scope and shared resources
- dependencies and precise unblock conditions
- positive/negative acceptance and required evidence
- state and last acknowledgment time

Use proposed → accepted → active → in_review → verified, with waiting/blocked
and remaining scope explicit. Proposed is not accepted; accepted is not active.
The worker acknowledges with its real session/branch identity before editing.
Follow the repository wip convention, then reread for competing claims.
These conventions are not an atomic distributed lock: resolve conflicting
claims before editing. A stale timestamp alone does not prove abandonment.

A owns delivery assignments. Workers read proposed work and acknowledge it;
if no assignment exists they may claim independent, unowned work within their
role and record it. Do not stall solely because A has not written a message.
Cross-domain reassignment must name owner, scope, and duration; it need not
create another session or require repeated user approval for routine work.
An unavailable worker is recorded as unacknowledged/waiting, not fictitiously
running. No assumed cross-app messaging or automatic session launch.

The coordinator never asks itself or the user to choose among X1/B/C/X2 when the
role contract and affected domain already determine the route. A watcher tick must
perform the cmux packet delivery and observe acknowledgment, perform A's integration step,
or record a precise external gate before acknowledging its backlog token. A textual
proposal without one of those outcomes leaves the token pending for the next tick.

For the local five-tab cmux setup, assume all five role sessions are already open,
authenticated, model-selected, and rooted in prepared checkouts. A submits work to
an existing idle role surface and never launches or recreates a session. Discover
current IDs with `cmux tree --all --id-format both`; map the
current role tab titles and inspect the target with `cmux read-screen`. Prefer
`hype-coordinate/scripts/wake_role.py`, first as a dry run and then with `--apply`.
It rejects busy/nonempty targets and validates packet IDs and allowed HypeProof
URLs before sending the complete prompt. It waits for a unique dispatch-attempt
marker to render, targets the same surface with an explicit Enter key, and accepts
only a running marker rendered after that attempt. Historical running text never
counts. If the attempt remains in the composer, the helper clears it and fails
closed. An Enter escape embedded in `cmux send` can stay inside the Codex composer
as multiline text. Never paste issue body text into a shell command. A helper
`submitted_pending_ack` result proves only marker-specific submission and an
observed new run, not the worker's GitHub ACK. Record `accepted` only after
the real session and branch identity appear in the shared record. If text remains
in the composer, cancel that exact dispatcher text and keep the token pending; do
not press Enter later or pretend delivery. If cmux or the target session is
unavailable, the record remains waiting. Never type or queue the next packet into
a busy surface. One active implementation packet per worker means the next backlog
token remains pending until that surface is idle.

## Execution and verification

Use one active implementation packet per worker and an isolated worktree.
Check overlapping PRs/claims before edits. Reserve shared App/browser/mic/8787
access for one session. Do not terminate others' processes or overwrite work.

Inspect criteria at task start; deliver through the required hype-pr
inspect → assessment → prepare → create flow. Refresh stale receipts rather
than bypassing them. Run required repository checks and meaningful positive
and negative tests; Lab web code requires its production build.

A owns integration order and executes merges after all applicable gates pass; the
worker owns its changes and CI fixes. X2 owns independent evidence. Fix findings
through the original owner unless A records an explicit transfer. Do not request
reviewers or wait for peer approval for ordinary Jay-hosted product delivery.

Old HANDOFF/DAG completion, change-impact completion, closed issues, and merged
PRs do not establish fulfillment. Record the exact revision, inputs, environment,
observed result, and limits. Distinguish test design, executed tests, actual
App/host behavior, human acceptance, and production release. Do not weaken
checks, manufacture observations, or replace user participation with fixtures.

When one task waits for approval, hardware, or a person, continue independent
work. Do not invent speculative features or unrelated refactors to stay busy.

## Cost-aware monitoring and dispatch

Continuous delivery does not mean five models continuously reread the same state.
Use one watcher owned by A. Prefer a supported GitHub event trigger. Otherwise A
uses one recurring task, the cheapest supported model, low reasoning, and the
deterministic `hype-coordinate/scripts/delivery_delta.py` gate with PyYAML about
every five minutes. The gate covers both GitHub Issues/Epics and PR delivery
state. Missing policy dependencies fail the tick; they never reduce
technical or evidence gates. Explicitly select the watcher model; do not inherit an expensive role
model by accident.

An unchanged gate result ends that watcher tick with no more reads, comments, or
role calls. A changed result submits work only to the role needed for the affected packet.
Basing a recurring prompt on full scratchpad or handoff reads is forbidden: the
gate runs before any skill, handoff, issue body, or repository read. Read those
only after the returned delta identifies the affected item. A context-limit tick
is a failed watcher and must be reset and reverified.
B/C/X1/X2 must not run their own periodic full-queue polling jobs. They may keep
their sessions, but idle sessions consume no model turns. High-capability models
are for derivation, implementation, review, and verification after a delta.

A model-capacity rejection is a temporary runner failure, not task completion,
an empty queue, or a usage-limit conclusion. Keep the work token pending and retry
once on a later watcher tick. After two consecutive X2 Astra capacity failures,
use GPT-5.6 Sol high for routine verification and record the model in the result;
return to Astra only for a disputed or high-risk acceptance judgment when capacity
is available. Do not tight-loop retries or mark a failed dispatch active.

The watcher state stores exact repo/item/revision, checks, reviews, merge state,
and an acknowledged pending-work ledger. On its first compatible run it places
all current PRs and existing Epic/Intent issues into a bounded backlog; later it
adds every changed issue or PR. A reconciles a returned item into GitHub and any
required role delivery, then removes it with `delivery_delta.py --ack TOKEN`.
Never acknowledge a proposed assignment before the target session actually accepts
or before the exact waiting gate is recorded. A failed or partial query is unknown,
never unchanged. A
heartbeat records observation but does not prove an open role accepted a packet;
A must verify acknowledgment and actual start.

## Merge authority and completion loop

Use canonical Harness policy and `scripts/hype-merge/monitor.py` to inspect checks,
dependencies, holds, and current-head state. For Jay-hosted HypeProof work, do not
request reviewers and do not treat a missing peer approval as a gate when GitHub
does not enforce it. A squash-merges the exact current head when required checks
pass, required X2 evidence is current, dependency order is satisfied, and no
explicit hold, failed check, changes-requested state, conflict, or unresolved
material product/security/business decision remains.

If GitHub technically enforces a non-author approval or a control-plane rule, keep
the item waiting at that exact gate. Do not weaken protection, invent approval, or
send a review request unless Jay gives an explicit per-PR instruction. Continue
independent work meanwhile.

After each merge, verify the merge SHA, main checks, and applicable deployment.
Recompute the queue because strict current-branch rules make sibling PRs stale.
Update the next branch in dependency order, preserve both sides of conflicts,
run affected checks, and request targeted X2 re-verification for changed heads.
Continue independent work while a real human gate waits.

Stop the watcher for explicit user cancellation or an actual runtime, usage,
permission, or tool limit. Preserve the cursor and exact blocker. Do not bypass
limits, invent approval, or claim a schedule or dispatch that was not verified.
