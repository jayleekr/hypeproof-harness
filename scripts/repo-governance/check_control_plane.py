#!/usr/bin/env python3
"""Enforce the control-plane human gate (policy/control-plane.yaml).

Two modes:

  --changed-files <file>     Read newline-separated changed paths (e.g. from
                             `git diff --name-only origin/main...HEAD`) and print
                             which touch control-plane paths. Exit 1 if any do
                             AND the required human gate is not satisfied.

  --pr <number>              Query the PR via gh: its changed files, its author,
                             its last pusher, and its approving reviews. Enforces:
                               * a control-plane PR needs >=1 approval from a
                                 human_approver who is NOT the author/last-pusher;
                               * the last pusher must not be an automation_actor;
                               * automation_actors must not be an approver.

Intended to run as a required CI status on pull_request so branch protection
makes the human gate blocking. Automation may open a control-plane PR but this
check keeps it un-mergeable until a human approves.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("ERROR: pyyaml required", file=sys.stderr)
    raise SystemExit(2)

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY = REPO_ROOT / "policy" / "control-plane.yaml"


def load_policy() -> dict:
    with POLICY.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def matches(path: str, patterns: list[str]) -> bool:
    for pat in patterns:
        # support trailing /** as "prefix" and plain fnmatch
        if pat.endswith("/**"):
            prefix = pat[:-3]
            if path == prefix or path.startswith(prefix + "/"):
                return True
        if fnmatch.fnmatch(path, pat):
            return True
    return False


def control_plane_hits(files: list[str], policy: dict) -> list[str]:
    patterns = [p["path"] for p in policy.get("protected_paths", [])]
    return [f for f in files if matches(f, patterns)]


def check_pr(number: str, policy: dict) -> list[str]:
    repo = policy["repo"]
    approvers = set(policy.get("human_approvers", []))
    automation = set(policy.get("automation_actors", []))

    files_raw = subprocess.run(
        ["gh", "pr", "view", number, "--repo", repo, "--json", "files,author,reviews,commits"],
        capture_output=True, text=True, timeout=30)
    if files_raw.returncode != 0:
        print(f"ERROR: gh pr view failed: {files_raw.stderr.strip()}", file=sys.stderr)
        raise SystemExit(2)
    pr = json.loads(files_raw.stdout)
    files = [f["path"] for f in pr.get("files", [])]

    hits = control_plane_hits(files, policy)
    if not hits:
        return []  # not a control-plane PR; nothing to enforce here

    problems: list[str] = []
    author = (pr.get("author") or {}).get("login", "")
    commits = pr.get("commits", [])
    last_pusher = ""
    if commits:
        last = commits[-1]
        # commit author login if available
        authors = last.get("authors") or []
        last_pusher = (authors[0].get("login") if authors else "") or author

    approvals = [r for r in pr.get("reviews", []) if r.get("state") == "APPROVED"]
    approver_logins = {(r.get("author") or {}).get("login", "") for r in approvals}

    if last_pusher in automation:
        problems.append(f"last pusher {last_pusher!r} is an automation actor — a human must push the final change.")
    if automation & approver_logins:
        problems.append(f"automation actor(s) {sorted(automation & approver_logins)} approved — approvals must be human.")

    valid_human = {a for a in approver_logins if a in approvers and a != author and a != last_pusher}
    if not valid_human:
        problems.append(
            "control-plane PR requires >=1 approval from a human_approver who is not the "
            f"author ({author!r}) or last pusher ({last_pusher!r}). "
            f"approvers seen: {sorted(approver_logins) or 'none'}."
        )

    header = f"control-plane PR #{number} touches protected paths: {hits}"
    return [header, *problems] if problems else []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--changed-files", help="file with newline-separated changed paths")
    g.add_argument("--pr", help="PR number to enforce the human gate on")
    args = ap.parse_args(argv)
    policy = load_policy()

    if args.changed_files:
        files = [l.strip() for l in Path(args.changed_files).read_text().splitlines() if l.strip()]
        hits = control_plane_hits(files, policy)
        if hits:
            print("CONTROL-PLANE change detected in:")
            for h in hits:
                print(f"  - {h}")
            print("\nThis PR must be reviewed and merged by a human maintainer "
                  "(non-author). Automation may not approve or merge it.")
            return 1
        print("OK: no control-plane paths touched.")
        return 0

    problems = check_pr(args.pr, policy)
    if problems:
        for p in problems:
            print(p)
        return 1
    print(f"OK: PR #{args.pr} control-plane gate satisfied (or not a control-plane PR).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
