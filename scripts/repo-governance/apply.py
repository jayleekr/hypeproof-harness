#!/usr/bin/env python3
"""Apply HypeProof repository governance policy through GitHub's API."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "repo-governance"))
from audit import load_policy, repo_full_name, validate_policy  # noqa: E402


def gh_api(path: str, *, method: str = "GET", body: dict | None = None) -> tuple[int, str]:
    cmd = ["gh", "api", path]
    if method != "GET":
        cmd.extend(["--method", method])
    if body is not None:
        cmd.extend(["--input", "-"])
        raw = json.dumps(body)
    else:
        raw = None
    proc = subprocess.run(cmd, input=raw, text=True, capture_output=True, cwd=ROOT)
    return proc.returncode, proc.stdout.strip() or proc.stderr.strip()


def apply_repo_settings(full: str, profile: dict, repo: dict, dry_run: bool) -> list[str]:
    repository = profile.get("repository", {})
    merge = repository.get("merge_methods", {})
    features = repository.get("features", {})
    body = {
        "delete_branch_on_merge": repository.get("delete_branch_on_merge"),
        "allow_auto_merge": repository.get("allow_auto_merge"),
        "allow_squash_merge": merge.get("squash"),
        "allow_merge_commit": merge.get("merge_commit"),
        "allow_rebase_merge": merge.get("rebase"),
    }
    if "issues" in features:
        body["has_issues"] = features["issues"]
    if "wiki" in features:
        body["has_wiki"] = features["wiki"]
    if "projects" in features:
        body["has_projects"] = features["projects"]
    body = {k: v for k, v in body.items() if v is not None}
    return apply_call(full, "repo_settings", f"repos/{full}", "PATCH", body, dry_run)


def apply_security(full: str, profile: dict, dry_run: bool) -> list[str]:
    desired = profile.get("security", {})
    if not desired:
        return []
    body = {"security_and_analysis": {key: {"status": value} for key, value in desired.items()}}
    return apply_call(full, "security", f"repos/{full}", "PATCH", body, dry_run, soft=True)


def apply_actions(full: str, repo: dict, profile: dict, dry_run: bool) -> list[str]:
    desired = profile.get("actions", {})
    if not desired:
        return []
    logs: list[str] = []
    body = {
        "default_workflow_permissions": desired.get("default_workflow_permissions"),
        "can_approve_pull_request_reviews": desired.get("can_approve_pull_request_reviews"),
    }
    body = {k: v for k, v in body.items() if v is not None}
    if body:
        logs.extend(apply_call(full, "actions.workflow", f"repos/{full}/actions/permissions/workflow", "PUT", body, dry_run, soft=True))

    general = {
        "enabled": desired.get("enabled"),
        "allowed_actions": desired.get("allowed_actions"),
    }
    general = {k: v for k, v in general.items() if v is not None}
    if general:
        logs.extend(apply_call(full, "actions.permissions", f"repos/{full}/actions/permissions", "PUT", general, dry_run, soft=True))

    if repo.get("visibility") == "public" and desired.get("fork_pr_approval"):
        logs.extend(apply_call(
            full,
            "actions.fork_pr_approval",
            f"repos/{full}/actions/permissions/fork-pr-contributor-approval",
            "PATCH",
            {"approval_policy": desired["fork_pr_approval"]},
            dry_run,
            soft=True,
        ))
    return logs


def apply_branch_protection(full: str, repo: dict, profile: dict, dry_run: bool) -> list[str]:
    desired = profile.get("branch_protection", {})
    if not desired:
        return []
    branch = desired.get("branch", repo.get("default_branch", "main"))
    reviews = desired.get("required_pull_request_reviews", {})
    checks = repo.get("required_status_checks", [])
    body = {
        "required_status_checks": {
            "strict": desired.get("required_status_checks", {}).get("strict", True),
            "contexts": checks,
        } if checks else None,
        "enforce_admins": desired.get("enforce_admins", True),
        "required_pull_request_reviews": {
            "dismiss_stale_reviews": reviews.get("dismiss_stale_reviews", False),
            "require_code_owner_reviews": reviews.get("require_code_owner_reviews", False),
            "required_approving_review_count": reviews.get("required_approving_review_count", 0),
            "require_last_push_approval": reviews.get("require_last_push_approval", False),
        },
        "restrictions": None,
        "required_linear_history": desired.get("required_linear_history", False),
        "allow_force_pushes": desired.get("allow_force_pushes", False),
        "allow_deletions": desired.get("allow_deletions", False),
        "required_conversation_resolution": True,
    }
    return apply_call(full, "branch_protection", f"repos/{full}/branches/{branch}/protection", "PUT", body, dry_run, soft=True)


def apply_call(
    full: str,
    module: str,
    path: str,
    method: str,
    body: dict,
    dry_run: bool,
    *,
    soft: bool = False,
) -> list[str]:
    if dry_run:
        return [f"DRY {full} {module} {method} {path} {json.dumps(body, sort_keys=True)}"]
    code, out = gh_api(path, method=method, body=body)
    if code == 0:
        return [f"OK  {full} {module}"]
    prefix = "WARN" if soft else "FAIL"
    msg = f"{prefix} {full} {module}: {out}"
    if soft:
        return [msg]
    raise RuntimeError(msg)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", help="owner/name or repo name from policy")
    parser.add_argument("--all", action="store_true", help="apply every repo")
    parser.add_argument("--dry-run", action="store_true", help="print planned API calls")
    parser.add_argument("--apply", action="store_true", help="mutate GitHub settings")
    args = parser.parse_args(argv)

    if args.apply == args.dry_run:
        print("choose exactly one: --dry-run or --apply", file=sys.stderr)
        return 64

    policy = load_policy()
    findings = validate_policy(policy)
    if findings:
        print(json.dumps({"status": "policy-invalid", "findings": [f.as_dict() for f in findings]}, indent=2))
        return 4

    selected = []
    for repo in policy["repos"].get("repositories", []):
        full = repo_full_name(repo)
        if args.all or args.repo in (full, repo.get("name")):
            selected.append(repo)
    if not selected:
        print("no repositories selected", file=sys.stderr)
        return 64

    logs: list[str] = []
    dry_run = args.dry_run
    for repo in selected:
        full = repo_full_name(repo)
        profile = policy["profiles"][repo["profile"]]
        logs.extend(apply_repo_settings(full, profile, repo, dry_run))
        logs.extend(apply_security(full, profile, dry_run))
        logs.extend(apply_actions(full, repo, profile, dry_run))
        logs.extend(apply_branch_protection(full, repo, profile, dry_run))
    print("\n".join(logs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
