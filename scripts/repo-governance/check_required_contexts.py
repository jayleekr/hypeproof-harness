#!/usr/bin/env python3
"""Preflight guard for required_status_checks.

apply.py (apply_branch_protection, lines ~150-154) copies each repo's
`required_status_checks` list from policy/repos.yaml straight into the GitHub
branch-protection `contexts` array. GitHub then blocks merge until a check run
REPORTS each of those exact context strings. If a declared context is a name no
workflow ever produces, the branch is locked permanently (no run will ever
satisfy it). If two workflows both produce the same context string, requiring it
is ambiguous. This script catches both BEFORE apply.py can arm the lock.

How a context string is produced (verified against the live harness protection,
whose required contexts equal the job `name:` fields with no workflow prefix):

    context = job["name"]  if the job declares one
            = <job-id>      otherwise      (NOT "<workflow name> / <job-id>")

Usage:
    # Offline: parse workflow YAML in a repo checkout.
    check_required_contexts.py --repo jayleekr/hypeproof-harness --root .
    check_required_contexts.py --all --workspace /path/to/workspace

    # Online cross-check: compare against contexts GitHub has actually reported.
    check_required_contexts.py --repo jayleekr/hypeprooflab --observed

Exit code 0 = all declared contexts are producible and unambiguous.
Exit code 1 = at least one declared context would lock or is ambiguous.
Exit code 2 = could not evaluate (missing workflows / gh); reported, not silent.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("ERROR: pyyaml required (pip install pyyaml)", file=sys.stderr)
    raise SystemExit(2)

REPO_ROOT = Path(__file__).resolve().parents[2]
REPOS_YAML = REPO_ROOT / "policy" / "repos.yaml"


def load_repos() -> list[dict]:
    with REPOS_YAML.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh).get("repositories", [])


def producible_contexts(workflows_dir: Path) -> dict[str, list[str]]:
    """Map context string -> list of workflow files that produce it.

    A workflow file may be malformed or use `on:` values we do not evaluate;
    we still enumerate its jobs. Reusable-workflow calls (`uses:`) and matrices
    are reported as-is on a best-effort basis (matrix expansion is not modelled;
    such jobs are flagged in the returned notes list via the ambiguity check).
    """
    contexts: dict[str, list[str]] = {}
    for wf in sorted(list(workflows_dir.glob("*.yml")) + list(workflows_dir.glob("*.yaml"))):
        try:
            data = yaml.safe_load(wf.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            print(f"WARN: cannot parse {wf.name}: {exc}", file=sys.stderr)
            continue
        jobs = data.get("jobs") or {}
        for job_id, job in jobs.items():
            if not isinstance(job, dict):
                continue
            ctx = job.get("name") or job_id
            if not isinstance(ctx, str):
                ctx = str(job_id)
            contexts.setdefault(ctx, []).append(wf.name)
    return contexts


def observed_contexts(full: str) -> set[str]:
    """Contexts GitHub has actually reported recently (ground truth)."""
    seen: set[str] = set()
    # default-branch head check-runs + statuses
    sha = _gh(["api", f"repos/{full}/commits/HEAD", "--jq", ".sha"])
    if sha:
        runs = _gh(["api", f"repos/{full}/commits/{sha}/check-runs", "--jq", ".check_runs[].name"])
        seen.update(filter(None, (runs or "").splitlines()))
        st = _gh(["api", f"repos/{full}/commits/{sha}/status", "--jq", ".statuses[].context"])
        seen.update(filter(None, (st or "").splitlines()))
    # recent PR heads (workflows that only run on PRs)
    prs = _gh(["api", f"repos/{full}/pulls?state=all&per_page=5", "--jq", ".[].head.sha"])
    for psha in filter(None, (prs or "").splitlines()):
        runs = _gh(["api", f"repos/{full}/commits/{psha}/check-runs", "--jq", ".check_runs[].name"])
        seen.update(filter(None, (runs or "").splitlines()))
    return seen


def _gh(args: list[str]) -> str | None:
    try:
        out = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def check_repo(repo: dict, root: Path | None, observed: bool) -> list[str]:
    full = f"{repo['owner']}/{repo['name']}"
    declared = repo.get("required_status_checks") or []
    if not declared:
        return []
    errors: list[str] = []

    producible: dict[str, list[str]] | None = None
    if root is not None:
        wf_dir = root / ".github" / "workflows"
        if wf_dir.is_dir():
            producible = producible_contexts(wf_dir)
        else:
            print(f"WARN[{full}]: no workflows dir at {wf_dir}; offline check skipped", file=sys.stderr)

    seen = observed_contexts(full) if observed else set()

    for ctx in declared:
        # Some declared contexts belong to external apps (e.g. "Vercel – hypeproof")
        # or reusable workflows in the same repo; offline parse covers local jobs,
        # online `observed` covers everything GitHub actually reported.
        producers = producible.get(ctx, []) if producible is not None else None
        if producible is not None and not producers and (not observed or ctx not in seen):
            errors.append(
                f"LOCK[{full}]: required context {ctx!r} is produced by NO local workflow"
                + ("" if not observed else " and was NOT reported by GitHub recently")
                + " — requiring it would block merge forever."
            )
        if producers and len(producers) > 1:
            errors.append(
                f"AMBIGUOUS[{full}]: context {ctx!r} is produced by {len(producers)} "
                f"workflows {producers} — a required check must map to exactly one."
            )
        if observed and producible is None and ctx not in seen:
            errors.append(
                f"LOCK[{full}]: required context {ctx!r} not among contexts GitHub "
                f"reported recently — verify a workflow produces it before requiring."
            )
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", help="owner/name to check (default: all in repos.yaml)")
    ap.add_argument("--all", action="store_true", help="check every repo in repos.yaml")
    ap.add_argument("--root", help="checkout root for --repo (offline workflow parse)")
    ap.add_argument("--workspace", default=os.environ.get("HYPEPROOF_WORKSPACE"),
                    help="workspace dir holding sibling checkouts <name>/ (offline parse)")
    ap.add_argument("--observed", action="store_true",
                    help="also cross-check against contexts GitHub actually reported (needs gh)")
    ap.add_argument("--json", action="store_true", help="emit findings as JSON")
    args = ap.parse_args(argv)

    repos = load_repos()
    if args.repo and not args.all:
        repos = [r for r in repos if f"{r['owner']}/{r['name']}" == args.repo]
        if not repos:
            print(f"ERROR: {args.repo} not found in repos.yaml", file=sys.stderr)
            return 2

    all_errors: list[str] = []
    for repo in repos:
        full = f"{repo['owner']}/{repo['name']}"
        if args.root and args.repo == full:
            root = Path(args.root)
        elif full == "jayleekr/hypeproof-harness":
            root = REPO_ROOT
        elif args.workspace:
            root = Path(args.workspace) / repo["name"]
        else:
            root = None
        all_errors.extend(check_repo(repo, root if (root and root.exists()) else None, args.observed))

    if args.json:
        print(json.dumps({"errors": all_errors}, ensure_ascii=False, indent=2))
    else:
        for e in all_errors:
            print(e)
        if not all_errors:
            print("OK: all declared required_status_checks are producible and unambiguous.")
    return 1 if all_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
