#!/usr/bin/env python3
"""hypeproof weekly-loop checker — validate cycle issues before the meeting.

Canonical source in hypeproof-harness; vendored into each consumer repo
(hypeproof-studio, sediment, hypeprooflab) via sync.sh. Intentionally uses
only the Python standard library so each product repo can vendor and run it
without bootstrapping a package manager. GitHub access goes through the `gh`
CLI — no tokens are read or stored here.

Rule under test (docs/WEEKLY-LOOP.ko.md §4): every OPEN issue carrying the
cycle label `weekly-YYYY-MM-DD` must have
  - an `ETA: YYYY-MM-DD` line whose date is <= the cycle date, and
  - an `Owner` / `담당` section or line.

USAGE:
    check.py --cycle weekly-2026-07-21
    check.py --cycle weekly-2026-07-21 --repo jayleekr/sediment
    check.py --cycle weekly-2026-07-21 --issues-json fixtures.json   # offline

`--issues-json` bypasses `gh` for deterministic tests: a JSON object mapping
"owner/name" to a list of gh-shaped issue dicts (number, title, body, url).

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


def parse_cycle_date(label: str) -> dt.date:
    m = CYCLE_RE.match(label)
    if not m:
        raise ValueError(
            f"bad cycle label {label!r} — expected weekly-YYYY-MM-DD (date of the NEXT Monday meeting)"
        )
    return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def gh_open_issues(repo: str, label: str) -> list[dict]:
    proc = subprocess.run(
        [
            "gh", "issue", "list",
            "--repo", repo,
            "--label", label,
            "--state", "open",
            "--limit", "200",
            "--json", "number,title,body,url",
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate that every open weekly-cycle issue has Owner + ETA <= cycle date."
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
    for repo in repos:
        try:
            issues = fixture.get(repo, []) if fixture is not None else gh_open_issues(repo, args.cycle)
        except RuntimeError as exc:
            print(f"ERROR  {exc}", file=sys.stderr)
            return 2

        print(f"\n{repo} — {len(issues)} open issue(s) with label {args.cycle}")
        for issue in issues:
            total += 1
            ref = f"#{issue.get('number', '?')} {issue.get('title', '(no title)')}"
            violations = check_issue(issue.get("body", ""), cycle_date)
            if violations:
                bad += 1
                print(f"  VIOLATION  {ref}")
                for reason in violations:
                    print(f"    - {reason}")
                if issue.get("url"):
                    print(f"    → {issue['url']}")
            else:
                print(f"  OK         {ref}")

    print(f"\nTotal: {total} issue(s) · {bad} violation(s)")
    if bad:
        print("✗ weekly-loop check failed — fix Owner/ETA before the meeting", file=sys.stderr)
        return 1
    print("✓ every cycle issue has Owner + ETA within the cycle")
    return 0


if __name__ == "__main__":
    sys.exit(main())
