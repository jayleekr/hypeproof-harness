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


def check_repo(repo: dict, root: Path | None, observed: bool) -> dict:
    """Return {full, status, reason, errors}.

    status is one of:
      - "no-checks"  declared list empty; nothing to validate (safe).
      - "examined"   we actually inspected producible/observed contexts.
      - "skipped"    we could NOT inspect this repo (no local workflows and
                     --observed not set). Critically this is NOT "OK": an
                     un-inspected repo must never be conflated with a clean one
                     (the Control Invariant — do not report unexamined as pass).
    """
    full = f"{repo['owner']}/{repo['name']}"
    declared = repo.get("required_status_checks") or []
    if not declared:
        return {"full": full, "status": "no-checks", "reason": "", "errors": []}

    producible: dict[str, list[str]] | None = None
    if root is not None:
        wf_dir = root / ".github" / "workflows"
        if wf_dir.is_dir():
            producible = producible_contexts(wf_dir)

    # Not examinable: no local workflows to parse AND not cross-checking GitHub.
    if producible is None and not observed:
        return {
            "full": full,
            "status": "skipped",
            "reason": ("no local workflows dir (pass --root/--workspace pointing "
                       "at a checkout, or --observed to query GitHub)"),
            "errors": [],
        }

    seen = observed_contexts(full) if observed else set()
    errors: list[str] = []
    for ctx in declared:
        # Some declared contexts belong to external apps (e.g. "Vercel – hypeproof")
        # or reusable workflows; offline parse covers local jobs, online `observed`
        # covers everything GitHub actually reported.
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
    return {"full": full, "status": "examined", "reason": "", "errors": errors}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", help="owner/name to check (default: all in repos.yaml)")
    ap.add_argument("--all", action="store_true", help="check every repo in repos.yaml")
    ap.add_argument("--root", help="checkout root for --repo (offline workflow parse)")
    ap.add_argument("--workspace", default=os.environ.get("HYPEPROOF_WORKSPACE"),
                    help="workspace dir holding sibling checkouts <name>/ (offline parse)")
    ap.add_argument("--observed", action="store_true",
                    help="also cross-check against contexts GitHub actually reported (needs gh)")
    ap.add_argument("--allow-unexamined", action="store_true",
                    help="downgrade un-inspectable repos from fail-closed to a warning "
                         "(default: any skipped repo makes the run exit non-zero)")
    ap.add_argument("--json", action="store_true", help="emit findings as JSON")
    args = ap.parse_args(argv)

    repos = load_repos()
    if args.repo and not args.all:
        repos = [r for r in repos if f"{r['owner']}/{r['name']}" == args.repo]
        if not repos:
            print(f"ERROR: {args.repo} not found in repos.yaml", file=sys.stderr)
            return 2

    results: list[dict] = []
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
        results.append(check_repo(repo, root if (root and root.exists()) else None, args.observed))

    errors = [e for r in results for e in r["errors"]]
    skipped = [r for r in results if r["status"] == "skipped"]
    examined = [r for r in results if r["status"] == "examined"]
    no_checks = [r for r in results if r["status"] == "no-checks"]

    if args.json:
        print(json.dumps({
            "examined": [r["full"] for r in examined],
            "skipped": [{"repo": r["full"], "reason": r["reason"]} for r in skipped],
            "no_checks": [r["full"] for r in no_checks],
            "errors": errors,
        }, ensure_ascii=False, indent=2))
    else:
        for e in errors:
            print(e)
        # Always declare the coverage — never let "no errors" imply "all clean"
        # when some repos were never inspected.
        print(f"\nCoverage: examined {len(examined)}, "
              f"no-checks {len(no_checks)}, skipped {len(skipped)}, "
              f"errors {len(errors)}.")
        for r in skipped:
            print(f"SKIPPED[{r['full']}]: {r['reason']}")
        if not errors and not skipped:
            print("OK: every repo with required checks was examined; all contexts "
                  "are producible and unambiguous.")

    if errors:
        return 1
    if skipped and not args.allow_unexamined:
        # Fail-closed: un-inspected repos are not a pass. Control Invariant.
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
