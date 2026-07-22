# weekly-harness

Deterministic validators for the HypeProof weekly operating loop
(`docs/WEEKLY-LOOP.ko.md`). Canonical source lives in `hypeproof-harness`;
vendored into each consumer repo (`hypeproof-studio`, `sediment`,
`hypeprooflab`) via `scripts/sync.sh` with a `HARNESS_VERSION` marker.

All three scripts are stdlib-only Python 3 and talk to GitHub through the `gh`
CLI — no tokens are read or stored.

## check.py — pre-meeting gate

For a cycle label (`weekly-YYYY-MM-DD` — the date of the NEXT Monday
meeting), across the three product repos:

**Open** issues carrying that label must have

- an `ETA: YYYY-MM-DD` line with a date `<=` the cycle date, and
- an `Owner` / `담당` section or line.

**Closed** issues carrying that label must have (원칙 4 — completion gate)

- an `Evidence: <url>` (or `증거: <url>`) line in the body or in any comment,
  where `<url>` is one of
  - `https://github.com/<owner>/<repo>/pull/<n>`
  - `https://github.com/<owner>/<repo>/commit/<sha>` (7–40 hex)
  - `https://github.com/<owner>/<repo>/issues/<n>#issuecomment-<id>`
- **or** an exemption: the `no-evidence-needed` label (administrative /
  non-deliverable work), or GitHub's "closed as not planned" state
  (cancelled — nothing was produced).

The ref reuses GitHub's own identifiers rather than a new registry, and needs
*both* the `Evidence:` marker and a permalink shape — a bare link pasted in a
body is ordinary issue chatter and must not satisfy the gate by accident.
Only the shape is checked; the checker does not fetch the URL, so a
well-formed ref to a nonexistent PR still passes. That is deliberate — the
gate is offline and deterministic, and a wrong permalink is visible to any
human who clicks it.

```bash
python3 scripts/weekly-harness/check.py --cycle weekly-2026-07-21
```

`--skip-evidence-gate` disables only the closed-issue rule. It exists for the
adoption window (issues closed before the gate landed have no `Evidence:`
line); it is not for CI.

Exit codes: `0` clean · `1` violations (each printed) · `2` config/gh error.

## burndown.py — Monday agenda report

Per repo: closed vs open counts for the cycle label plus a table of every
issue (number, title, owner, state). Markdown on stdout — paste it at the
top of the weekly agenda or pipe it into `scripts/notify/notify.py`.

```bash
python3 scripts/weekly-harness/burndown.py --cycle weekly-2026-07-21
```

Exit codes: `0` report generated · `2` config/gh error.

## announce.py — Tuesday broadcast

The human-facing announcement for a cycle: what each member owns this cycle
(grouped by owner across all repos), what carried over unfinished from last
cycle, and how the tracked milestones (workshop dates) are progressing.
Markdown on stdout — publish it as an Artifact and/or post to Discord.

```bash
python3 scripts/weekly-harness/announce.py --cycle weekly-2026-07-27
```

`--prev-cycle` defaults to the Monday one week earlier (the carry-over
source). `--milestone-repo` limits which repos' milestones are read (default:
same as `--repo`). Exit codes: `0` generated · `2` config/gh error.

## Offline / testing

`--issues-json <path>` feeds gh-shaped issue fixtures
(`{"owner/name": [issue, ...]}`) instead of calling `gh`, so
`tests/weekly_loop/` runs deterministically without network or auth.

## Vendoring

Registered in `sync.sh` `SCRIPTS=()`. Fix here and re-sync — never edit the
vendored copies in consumer repos.
