#!/usr/bin/env python3
"""Verify a PR body's `Closes #<n>` references point at issues that exist.

Companion to the `pr-policy` workflow step. The old check was a pure regex —
`grep -qE '(Closes|Fixes|Resolves) #[0-9]+'` — so it validated *form*, not
*existence*: `Closes #999999` (no such issue) and `Fixes #0` both passed. That
is the same defect class as an evidence gate that accepts a well-formed link to
work nobody did — a reference is only a reference if the thing it names is real.

This tool keeps the form requirement (a PR must still declare what it closes)
and adds an existence requirement: every referenced number must resolve to an
issue or PR *in the repository under review*, via `gh`. A typo'd or invented
number now fails with a message that names the number, instead of passing.

Existence is checked in the repo the PR targets — GitHub's own linking keywords
only auto-close issues in the same repo, so a same-repo `#<n>` is the only form
that has ever done anything. Cross-repo `owner/repo#n` was already rejected by
the old ` #<n>` shape and stays out of scope here.

Deliberately std-lib only and gh-via-subprocess, matching check.py: the harness
is vendored into consumer repos that must run it without a package manager.

USAGE (in CI, from the pr-policy step):
    printf '%s' "$PR_BODY" | python3 verify_pr_closes.py --repo "$GITHUB_REPOSITORY"

    python3 verify_pr_closes.py --repo owner/name --body "Fixes #12"
    python3 verify_pr_closes.py --repo owner/name --body "..." --json

    # offline/deterministic tests: {"12": true, "13": false} — true = resolves
    python3 verify_pr_closes.py --repo owner/name --body "Closes #12" \
        --refs-json fixtures.json

EXIT CODES:
    0  the body declares ≥1 close ref and every referenced number resolves
    1  no close ref, or a referenced number does not resolve (each is printed)
    2  config error / gh could-not-verify (fail closed — an unverifiable ref is
       not a verified one)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# The three GitHub auto-closing keywords the policy accepts, then ` #<n>`.
CLOSES_RE = re.compile(r"\b(?:Closes|Fixes|Resolves)\s+#(\d+)\b", re.IGNORECASE)

# gh prints this (or a close variant) when a number names nothing. Distinguished
# from transport/auth errors so a real 404 fails the PR (exit 1) while an API
# hiccup fails closed as could-not-verify (exit 2) rather than passing.
NOT_FOUND_MARKERS = (
    "could not resolve to an issue or pull request",
    "could not resolve to a node",
    "no issue or pull request found",
    "not found",
)


def parse_refs(body: str) -> list[int]:
    """Unique referenced issue numbers, in first-seen order."""
    seen: dict[int, None] = {}
    for m in CLOSES_RE.finditer(body or ""):
        seen.setdefault(int(m.group(1)), None)
    return list(seen)


def _gh_resolves(repo: str, number: int) -> bool | None:
    """True if #number is a real issue or PR in repo, False if GitHub says it is
    not, None if we could not tell (auth/transport) — the caller fails closed.
    """
    for kind in ("issue", "pr"):
        proc = subprocess.run(
            ["gh", kind, "view", str(number), "--repo", repo, "--json", "number"],
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode == 0:
            return True
        blob = (proc.stderr + proc.stdout).lower()
        if not any(marker in blob for marker in NOT_FOUND_MARKERS):
            # An error that is NOT "no such thing" — e.g. auth or network. We do
            # not know whether the ref exists; do not guess.
            return None
    # Both `issue view` and `pr view` said "not found": the number is unreal.
    return False


def provenance(repo: str) -> dict:
    """Who/what/where, for the audit trail (Control Invariant)."""
    operator = (
        os.environ.get("GITHUB_ACTOR")
        or os.environ.get("USER")
        or os.environ.get("LOGNAME")
        or "unknown"
    )
    environment = "github-actions" if os.environ.get("GITHUB_ACTIONS") else "local"
    try:
        import hashlib
        version = "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]
    except OSError:
        version = "sha256:unknown"
    return {
        "operator": operator,
        "environment": environment,
        "verifier_version": version,
        "repo": repo,
    }


def verify(body: str, repo: str, resolver) -> dict:
    """Classify one PR body. resolver(repo, n) -> bool | None.

    Returns {"status", "refs", "resolved", "missing", "unverifiable"}.
    """
    refs = parse_refs(body)
    if not refs:
        return {"status": "no_ref", "refs": [], "resolved": [],
                "missing": [], "unverifiable": []}

    resolved: list[int] = []
    missing: list[int] = []
    unverifiable: list[int] = []
    for number in refs:
        verdict = resolver(repo, number)
        if verdict is True:
            resolved.append(number)
        elif verdict is False:
            missing.append(number)
        else:
            unverifiable.append(number)

    if unverifiable:
        status = "unverifiable"
    elif missing:
        status = "missing"
    else:
        status = "ok"
    return {"status": status, "refs": refs, "resolved": resolved,
            "missing": missing, "unverifiable": unverifiable}


def coverage_lines(result: dict, prov: dict) -> list[str]:
    def fmt(nums: list[int]) -> str:
        return ", ".join(f"#{n}" for n in nums) if nums else "(none)"

    return [
        "",
        "## Coverage — PR close refs",
        f"- repo under review:              {prov['repo']}",
        f"- close refs declared:            {len(result['refs'])} ({fmt(result['refs'])})",
        f"- resolved to a real issue/PR:    {len(result['resolved'])} ({fmt(result['resolved'])})",
        f"- referenced but nonexistent:     {len(result['missing'])} ({fmt(result['missing'])})",
        f"- could not verify (failed closed):{len(result['unverifiable'])} ({fmt(result['unverifiable'])})",
        "",
        "## Provenance — who/what/where enforced this",
        f"- operator:                       {prov['operator']}",
        f"- environment:                    {prov['environment']}",
        f"- verifier version:               {prov['verifier_version']}",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify a PR body's Closes/Fixes/Resolves #<n> refs point at issues "
                    "that actually exist in the repo under review."
    )
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY", ""),
        metavar="OWNER/NAME",
        help="repo the PR targets (default: $GITHUB_REPOSITORY)",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--body", help="PR body text (default: read stdin)")
    group.add_argument("--body-file", metavar="PATH", help="read the PR body from a file")
    parser.add_argument(
        "--refs-json",
        metavar="PATH",
        help='offline fixture: JSON {"<n>": true|false} instead of gh (true = resolves)',
    )
    parser.add_argument("--json", dest="as_json", action="store_true",
                        help="emit a machine-readable report on stdout")
    args = parser.parse_args(argv)

    if not args.repo:
        print("ERROR  --repo is required (or set GITHUB_REPOSITORY)", file=sys.stderr)
        return 2

    if args.body is not None:
        body = args.body
    elif args.body_file:
        try:
            body = Path(args.body_file).read_text(encoding="utf-8")
        except OSError as exc:
            print(f"ERROR  cannot read --body-file {args.body_file}: {exc}", file=sys.stderr)
            return 2
    else:
        body = sys.stdin.read()

    if args.refs_json:
        try:
            table = json.loads(Path(args.refs_json).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"ERROR  cannot read fixture {args.refs_json}: {exc}", file=sys.stderr)
            return 2

        def resolver(repo: str, number: int):
            # Absent key => unknown => fail closed (None), never a silent pass.
            return table.get(str(number))
    else:
        resolver = _gh_resolves

    result = verify(body, args.repo, resolver)
    prov = provenance(args.repo)

    if args.as_json:
        print(json.dumps({"result": result, "provenance": prov}, ensure_ascii=False, indent=2))
    else:
        print("\n".join(coverage_lines(result, prov)))

    if result["status"] == "no_ref":
        print(
            "PR body must include 'Closes #<n>', 'Fixes #<n>', or 'Resolves #<n>' "
            "naming the issue it closes (MEMBER-GUIDE.ko.md §4.4)",
            file=sys.stderr,
        )
        return 1
    if result["status"] == "unverifiable":
        nums = ", ".join(f"#{n}" for n in result["unverifiable"])
        print(
            f"could not verify close ref(s) {nums} against {args.repo} — gh returned an "
            "error that is not 'not found' (auth/network?). Failing closed: an "
            "unverifiable reference has not been verified.",
            file=sys.stderr,
        )
        return 2
    if result["status"] == "missing":
        nums = ", ".join(f"#{n}" for n in result["missing"])
        print(
            f"PR body references {nums}, which do not exist in {args.repo} — a typo'd or "
            "invented issue number is not a real close reference. Reference an issue "
            "that exists.",
            file=sys.stderr,
        )
        return 1

    print(
        f"✓ {len(result['resolved'])} close ref(s) resolved in {args.repo}",
        file=sys.stderr if args.as_json else sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
