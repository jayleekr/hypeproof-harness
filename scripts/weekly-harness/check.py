#!/usr/bin/env python3
"""hypeproof weekly-loop checker — validate cycle issues before the meeting.

Canonical source in hypeproof-harness; vendored into each consumer repo
(hypeproof-studio, sediment, hypeprooflab) via sync.sh. Intentionally uses
only the Python standard library so each product repo can vendor and run it
without bootstrapping a package manager. GitHub access goes through the `gh`
CLI — no tokens are read or stored here.

Two rules, one per side of an issue's life:

OPEN issues (docs/WEEKLY-LOOP.ko.md §4) carrying the cycle label
`weekly-YYYY-MM-DD` must have
  - an `ETA: YYYY-MM-DD` line whose date is <= the cycle date, and
  - an `Owner` / `담당` section or line.

CLOSED issues (§2 원칙 4 — "산출물은 증거로 축적돼야 완료") must either
  - reference evidence: an `Evidence: <url>` (or `증거: <url>`) line in the
    issue body or in any comment, where <url> is a GitHub permalink to the
    thing that was produced — a PR, a commit, or an issue comment; or
  - carry an explicit exemption: the `no-evidence-needed` label (administrative
    / non-deliverable work), or GitHub's own "closed as not planned"
    state (cancelled work).

The evidence ref deliberately reuses GitHub's existing identifiers instead of
inventing a namespace, and deliberately requires both the `Evidence:` marker
and a permalink shape — a bare link pasted in a body does not accidentally
satisfy the gate, and a satisfied gate always points at something a human can
open. Shape is checked offline; existence is not (see README).

USAGE:
    check.py --cycle weekly-2026-07-21
    check.py --cycle weekly-2026-07-21 --repo jayleekr/sediment
    check.py --cycle weekly-2026-07-21 --issues-json fixtures.json   # offline
    check.py --cycle weekly-2026-07-21 --skip-evidence-gate          # transition only

`--issues-json` bypasses `gh` for deterministic tests: a JSON object mapping
"owner/name" to a list of gh-shaped issue dicts (number, title, body, url,
state, stateReason, labels, comments). An issue with no `state` key is treated
as OPEN.

EXIT CODES:
    0  every cycle issue conforms
    1  violations found (each is printed)
    2  config error / bad cycle label / gh failure
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_REPOS = [
    "jayleekr/hypeprooflab",
    "jayleekr/hypeproof-studio",
    "jayleekr/sediment",
]

CYCLE_RE = re.compile(r"^weekly-(\d{4})-(\d{2})-(\d{2})$")
ETA_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?ETA(?:\*\*)?\s*[:：]\s*(\S+)", re.IGNORECASE | re.MULTILINE
)
# '## ETA' heading with the date on the first non-empty line below it
# (e.g. issues filed before the inline 'ETA:' template existed)
ETA_HEADING_RE = re.compile(
    r"^\s*#{1,6}\s+(?:\*\*)?ETA(?:\*\*)?\s*$\n+\s*(?:\*\*)?(\S+)",
    re.IGNORECASE | re.MULTILINE,
)
OWNER_RE = re.compile(
    r"^\s*(?:#{1,6}\s+(?:\*\*)?(?:Owner|담당자?)(?:\*\*)?\s*$"  # '## Owner' / '## 담당' heading
    r"|(?:[-*]\s*)?(?:\*\*)?(?:Owner|담당자?)(?:\*\*)?\s*[:：])",
    re.IGNORECASE | re.MULTILINE,
)
# 'Evidence: <url>' / '증거: <url>' — same line shape as the ETA marker above.
EVIDENCE_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?(?:Evidence|증거)(?:\*\*)?\s*[:：]\s*(\S+)",
    re.IGNORECASE | re.MULTILINE,
)
# The ref must be a GitHub permalink to something that was actually produced.
# Reusing GitHub's identifiers keeps the gate verifiable without a new registry.
EVIDENCE_URL_RE = re.compile(
    r"^https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/"
    r"(?:pull/\d+"                     # PR that carried the work
    r"|commit/[0-9a-f]{7,40}"          # commit that landed it
    r"|issues/\d+\#issuecomment-\d+)$"  # comment holding the deliverable/report
)
EXEMPT_LABEL = "no-evidence-needed"


def parse_cycle_date(label: str) -> dt.date:
    m = CYCLE_RE.match(label)
    if not m:
        raise ValueError(
            f"bad cycle label {label!r} — expected weekly-YYYY-MM-DD (date of the NEXT Monday meeting)"
        )
    return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def gh_cycle_issues(repo: str, label: str) -> list[dict]:
    proc = subprocess.run(
        [
            "gh", "issue", "list",
            "--repo", repo,
            "--label", label,
            "--state", "all",
            "--limit", "200",
            "--json", "number,title,body,url,state,stateReason,labels,comments",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip()
        raise RuntimeError(f"gh issue list failed for {repo}: {detail}")
    return json.loads(proc.stdout or "[]")


def check_issue(body: str, cycle_date: dt.date) -> list[str]:
    """Return human-readable violation reasons for one issue body."""
    violations: list[str] = []
    body = body or ""

    m = ETA_RE.search(body) or ETA_HEADING_RE.search(body)
    if not m:
        violations.append("missing 'ETA:' line")
    else:
        raw = m.group(1).strip().rstrip(".,;)").strip("*")  # tolerate 'ETA: **2026-07-21**'
        try:
            eta = dt.date.fromisoformat(raw)
        except ValueError:
            violations.append(f"unparseable ETA date {raw!r} (want YYYY-MM-DD)")
        else:
            if eta > cycle_date:
                violations.append(
                    f"ETA {eta.isoformat()} is after the cycle date {cycle_date.isoformat()} — "
                    "split into a first deliverable due by Monday"
                )

    if not OWNER_RE.search(body):
        violations.append("missing 'Owner'/담당 section")

    return violations


def is_open(issue: dict) -> bool:
    """Absent state means open — keeps pre-existing Owner/ETA fixtures valid."""
    return str(issue.get("state") or "OPEN").upper() == "OPEN"


def issue_label_names(issue: dict) -> set[str]:
    names: set[str] = set()
    for label in issue.get("labels") or []:
        name = label.get("name") if isinstance(label, dict) else label
        if name:
            names.add(str(name))
    return names


def evidence_exemption(issue: dict) -> str | None:
    """Why this closed issue is allowed to skip the evidence gate, or None."""
    if EXEMPT_LABEL in issue_label_names(issue):
        return f"`{EXEMPT_LABEL}` label — administrative / non-deliverable"
    if str(issue.get("stateReason") or "").upper() == "NOT_PLANNED":
        return "closed as not planned — cancelled, nothing was produced"
    return None


def evidence_sources(issue: dict) -> list[str]:
    """Body plus every comment — evidence normally lands in the closing comment."""
    texts = [issue.get("body") or ""]
    for comment in issue.get("comments") or []:
        if isinstance(comment, dict):
            texts.append(comment.get("body") or "")
        elif isinstance(comment, str):
            texts.append(comment)
    return texts


def check_closed_issue(issue: dict) -> list[str]:
    """Return violation reasons for one closed issue (evidence gate, 원칙 4)."""
    malformed: list[str] = []
    for text in evidence_sources(issue):
        for m in EVIDENCE_RE.finditer(text):
            raw = m.group(1).strip().rstrip(".,;)").strip("*")
            if EVIDENCE_URL_RE.match(raw):
                return []
            malformed.append(raw)

    if malformed:
        return [
            f"malformed Evidence ref {raw!r} — want a GitHub PR, commit, or "
            "issue-comment URL (https://github.com/<owner>/<repo>/pull/<n>)"
            for raw in dict.fromkeys(malformed)
        ]
    return [
        "closed with no 'Evidence:' ref (WEEKLY-LOOP §2 원칙 4) — add "
        "`Evidence: <PR/commit/comment URL>` in the body or a comment, "
        f"or label the issue `{EXEMPT_LABEL}` if it produced no deliverable"
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate weekly-cycle issues: open ones carry Owner + ETA <= cycle "
                    "date, closed ones reference evidence or an explicit exemption."
    )
    parser.add_argument("--cycle", required=True, help="cycle label, e.g. weekly-2026-07-21")
    parser.add_argument(
        "--repo",
        action="append",
        dest="repos",
        metavar="OWNER/NAME",
        help=f"repo to check (repeatable; default: {', '.join(DEFAULT_REPOS)})",
    )
    parser.add_argument(
        "--issues-json",
        metavar="PATH",
        help='offline fixture: JSON {"owner/name": [issue, ...]} instead of gh',
    )
    parser.add_argument(
        "--skip-evidence-gate",
        action="store_true",
        help="do not check closed issues for an Evidence ref (transition window only)",
    )
    args = parser.parse_args(argv)

    try:
        cycle_date = parse_cycle_date(args.cycle)
    except ValueError as exc:
        print(f"ERROR  {exc}", file=sys.stderr)
        return 2

    repos = args.repos or DEFAULT_REPOS

    fixture: dict[str, list[dict]] | None = None
    if args.issues_json:
        try:
            fixture = json.loads(Path(args.issues_json).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"ERROR  cannot read fixture {args.issues_json}: {exc}", file=sys.stderr)
            return 2

    print(f"# weekly-loop check — cycle {args.cycle} (due {cycle_date.isoformat()})")
    total = 0
    bad = 0
    exempt = 0
    for repo in repos:
        try:
            issues = (
                fixture.get(repo, []) if fixture is not None
                else gh_cycle_issues(repo, args.cycle)
            )
        except RuntimeError as exc:
            print(f"ERROR  {exc}", file=sys.stderr)
            return 2

        print(f"\n{repo} — {len(issues)} issue(s) with label {args.cycle}")
        for issue in issues:
            total += 1
            ref = f"#{issue.get('number', '?')} {issue.get('title', '(no title)')}"

            if is_open(issue):
                violations = check_issue(issue.get("body", ""), cycle_date)
            elif args.skip_evidence_gate:
                print(f"  SKIP       {ref} (closed; evidence gate skipped)")
                continue
            else:
                reason = evidence_exemption(issue)
                if reason:
                    exempt += 1
                    print(f"  EXEMPT     {ref} — {reason}")
                    continue
                violations = check_closed_issue(issue)

            if violations:
                bad += 1
                print(f"  VIOLATION  {ref}")
                for reason in violations:
                    print(f"    - {reason}")
                if issue.get("url"):
                    print(f"    → {issue['url']}")
            else:
                print(f"  OK         {ref}")

    summary = f"\nTotal: {total} issue(s) · {bad} violation(s)"
    if exempt:
        summary += f" · {exempt} exempt"
    print(summary)
    if bad:
        print(
            "✗ weekly-loop check failed — open issues need Owner/ETA, "
            "closed issues need an Evidence ref or an exemption",
            file=sys.stderr,
        )
        return 1
    print("✓ open issues have Owner + ETA within the cycle; closed issues have evidence")
    return 0


if __name__ == "__main__":
    sys.exit(main())
