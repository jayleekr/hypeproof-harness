---
name: weekly-loop
description: Decompose HypeProof weekly meeting notes into GitHub issues with Context/Tasks/Owner/ETA, filed to the right product repo under the weekly-YYYY-MM-DD cycle label. Use this whenever the user provides meeting notes to break down, asks to run the weekly loop, file this week's action items, create cycle issues, or says "주간 루프", "회의록 분해", "이슈로 만들어", or "/weekly-loop" with a notes path. Also use it to run the pre-meeting burndown or the Owner/ETA check for a cycle.
---

# weekly-loop

Turn a Monday meeting-notes file into tracked, deadlined GitHub issues — the
Tuesday "AI decomposition" step of the weekly operating loop. The rules live
in `docs/WEEKLY-LOOP.ko.md`; this skill executes them. The point is not to
file many issues. The point is that every action item becomes an issue with
an Owner and an ETA before the next Monday meeting — unrecorded work does
not exist.

The deterministic validators are:

```bash
python3 scripts/weekly-harness/check.py --cycle weekly-<YYYY-MM-DD>
python3 scripts/weekly-harness/burndown.py --cycle weekly-<YYYY-MM-DD>
```

Run everything from the repo root. Humans set direction: always show the
drafted issues and get confirmation before filing (원칙 3 — 사람은 방향,
AI는 실행).

---

## Default Flow

1. Read the meeting notes.

   The user passes a markdown file path (e.g.
   `/weekly-loop meeting-notes/2026-07-14.md`). Read the whole file before
   drafting anything. If no path was given, ask for one.

2. Compute the cycle label — the date of the NEXT Monday meeting, KST.

   ```bash
   python3 -c "import datetime as d; t=d.datetime.now(d.timezone(d.timedelta(hours=9))).date(); print('weekly-'+(t+d.timedelta(days=(7-t.weekday())%7 or 7)).isoformat())"
   ```

   Run on the decomposition day (typically Tuesday) this yields the coming
   Monday. If the meeting notes are dated, sanity-check the label is the
   Monday after that date; when in doubt, confirm with the user.

3. Extract action items.

   An action item is anything the team agreed someone will do: explicit
   TODOs, "다음 주까지", "~하기로 함", decisions that imply work. Skip pure
   status updates and discussion without a commitment. For each item capture:
   what, why (the surrounding context), who (if named), and any deadline
   mentioned.

4. Map each item to its repo.

   | Item is about | Repo |
   |---|---|
   | 공개 사이트 · 콘텐츠 · 운영 · 멤버/커뮤니티 | `jayleekr/hypeprooflab` |
   | Studio 제품 (VSCodium fork · 워크숍 도구 · Worker) | `jayleekr/hypeproof-studio` |
   | 지식 DB · ingest · SaaS 백엔드/프론트 | `jayleekr/sediment` |
   | 공유 규약 · 스킬 · 프로세스 자체 | `jayleekr/hypeproof-harness` |

   Ambiguous items go to the repo where the deliverable will finally live.
   An item spanning repos becomes one issue per repo.

5. Draft each issue with the four required sections.

   Title: imperative, one line, no cycle date in it. Body template:

   ```markdown
   ## Context

   <why this exists — meeting-notes excerpt/summary, enough that an agent
   can pick it up without asking>

   ## Tasks

   - [ ] <concrete step>
   - [ ] <concrete step>

   ## Owner

   담당: @<github-id>

   ## ETA

   ETA: <YYYY-MM-DD>
   ```

   ETA must be on or before the cycle date. If an item is too big to finish
   by Monday, do not stretch the ETA — narrow the issue to a first
   deliverable (design doc, prototype, findings report) due by Monday and
   note the follow-up in Context. If no owner was named in the meeting,
   ask the user rather than guessing.

6. Dedup against open issues before filing.

   ```bash
   gh issue list --repo <owner/name> --state open --limit 100 --json number,title,labels
   gh issue list --repo <owner/name> --state open --search "<key words from title>" --json number,title,url
   ```

   If an open issue already covers the item, do not file a duplicate —
   comment the new context on the existing issue instead, and ensure it
   carries the cycle label and a valid ETA (add/update if the user agrees).

7. Show the full plan (repo, title, body, dedup verdicts) and get the
   user's confirmation. Apply their edits.

8. Ensure the cycle label exists in every target repo, then file.

   ```bash
   gh label create "weekly-<YYYY-MM-DD>" --repo <owner/name> \
     --description "Weekly cycle due <YYYY-MM-DD>" --color "1D76DB" 2>/dev/null || true

   gh issue create --repo <owner/name> \
     --title "<title>" \
     --body-file <drafted-body.md> \
     --label "weekly-<YYYY-MM-DD>" \
     --assignee <github-id>
   ```

   Write each drafted body to a temp file and pass `--body-file` so
   markdown survives quoting.

9. Verify and report.

   ```bash
   python3 scripts/weekly-harness/check.py --cycle weekly-<YYYY-MM-DD>
   ```

   Fix any violation it reports (edit the issue body via
   `gh issue edit <n> --repo <owner/name> --body-file ...`). Then report to
   the user: every created issue URL grouped by repo, items skipped as
   duplicates (with the existing issue URL), and items that still need an
   owner or a decision.

---

## Burndown mode

When the user asks for the pre-meeting report ("번다운", "burndown",
"이번 주 정리") instead of decomposition:

```bash
python3 scripts/weekly-harness/burndown.py --cycle weekly-<YYYY-MM-DD>
```

Paste the markdown output for the user (it goes at the top of the Monday
agenda). Open issues are carried over (new cycle label + new ETA) or dropped
in the meeting — offer to apply carry-overs with `gh issue edit`.

---

## Guardrails

- Never file issues without showing the drafts and getting confirmation.
- Never invent an owner — ask.
- Never set an ETA after the cycle date — split the work instead.
- One issue closes in one repo; split cross-repo items.
- No secrets in issue bodies; meeting notes may contain internal detail —
  summarize, do not paste tokens/URLs with credentials.
