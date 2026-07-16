#!/usr/bin/env python3
"""Plan and execute HypeProof pull request workflow policy.

This tool is intentionally conservative:

- every active member is requested as a reviewer, excluding the PR author
- auto-merge is opt-in and only enabled when repo policy allows it and the
  detected risk is low enough
- dry-run is the default for commands that would mutate GitHub
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "repo-governance"))
from audit import load_policy, repo_full_name, validate_policy  # noqa: E402


DEFAULT_OWNER = "jayleekr"
DEFAULT_BASE = "main"
AUTO_MERGE_METHOD = "squash"


PATH_RISK_RULES: tuple[tuple[str, str], ...] = (
    (r"(^|/)(auth|admin|oauth|secret|token|credential|permission|rbac)", "security"),
    (r"SECURITY\.md|\.pem$|\.key$|\.env", "security"),
    (r"(^|/)\.github/workflows/|vercel|fly\.toml|wrangler|deploy|release", "deploy"),
    (r"(^|/)(migrations?|sql|schema|tenant|rls|database|data)/|\.sql$", "data"),
    (r"package-lock\.json|pnpm-lock\.yaml|yarn\.lock|requirements.*\.txt|pyproject\.toml|Cargo\.lock", "dependency"),
    (r"CODEOWNERS|branch[_-]?protection|policy/|repo-governance", "governance"),
    (r"(^|/)docs?/|README|AGENTS|CLAUDE|OPENCLAW|\.md$", "docs"),
    (r"(^|/)(frontend|app|components|pages|public)/|\.tsx?$|\.css$", "ui"),
)

AUTO_MERGE_BLOCKING_RISKS = {"security", "deploy", "data", "dependency", "governance"}
AUTO_MERGE_BLOCKING_LABELS = {
    "human-needed",
    "security",
    "deploy",
    "data",
    "incident",
    "breaking-change",
    "do-not-merge",
}


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


def uniq(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value not in out:
            out.append(value)
    return out


def parse_repo(value: str) -> str:
    if "/" in value:
        owner, name = value.split("/", 1)
        if owner and name:
            return value
    return f"{DEFAULT_OWNER}/{value}"


def active_members(policy: dict[str, Any]) -> list[str]:
    members = policy.get("members", {}).get("members", {})
    return uniq(list(members.get("admins", [])) + list(members.get("writers", [])))


def reviewers_for_author(policy: dict[str, Any], author: str | None) -> list[str]:
    author_norm = (author or "").lstrip("@").lower()
    return [
        login
        for login in active_members(policy)
        if login.lower() != author_norm
    ]


def find_repo(policy: dict[str, Any], repo_ref: str) -> tuple[dict[str, Any], dict[str, Any]]:
    wanted = parse_repo(repo_ref)
    for repo in policy["repos"].get("repositories", []):
        full = repo_full_name(repo)
        if wanted in (full, repo.get("name")):
            return repo, policy["profiles"][repo["profile"]]
    raise ValueError(f"unknown repo in policy: {repo_ref}")


def detect_risks(paths: list[str]) -> list[str]:
    risks: list[str] = []
    for path in paths:
        for pattern, risk in PATH_RISK_RULES:
            if re.search(pattern, path, flags=re.IGNORECASE) and risk not in risks:
                risks.append(risk)
    return risks


def required_checks(repo: dict[str, Any]) -> list[str]:
    return list(repo.get("required_status_checks") or [])


def plan(
    *,
    policy: dict[str, Any],
    repo_ref: str,
    author: str | None,
    paths: list[str],
    labels: list[str],
    draft: bool,
    auto_merge: bool,
) -> dict[str, Any]:
    repo, profile = find_repo(policy, repo_ref)
    full = repo_full_name(repo)
    profile_repo = profile.get("repository", {})
    risks = detect_risks(paths)
    reviewer_logins = reviewers_for_author(policy, author)
    profile_allows_auto_merge = bool(profile_repo.get("allow_auto_merge"))
    checks = required_checks(repo)

    blockers: list[str] = []
    if not auto_merge:
        blockers.append("auto_merge_not_requested")
    if draft:
        blockers.append("draft_pr")
    if not profile_allows_auto_merge:
        blockers.append("profile_disallows_auto_merge")
    if not checks:
        blockers.append("no_required_status_checks_declared")
    for risk in risks:
        if risk in AUTO_MERGE_BLOCKING_RISKS:
            blockers.append(f"risk:{risk}")
    for label in labels:
        if label in AUTO_MERGE_BLOCKING_LABELS:
            blockers.append(f"label:{label}")

    return {
        "status": "planned",
        "repo": full,
        "profile": repo.get("profile"),
        "author": author,
        "reviewers": reviewer_logins,
        "review_request": {
            "active_members": active_members(policy),
            "exclude_author": True,
            "requested_reviewers": reviewer_logins,
        },
        "risk": {
            "paths": paths,
            "detected": risks,
            "auto_merge_blocking": [risk for risk in risks if risk in AUTO_MERGE_BLOCKING_RISKS],
        },
        "auto_merge": {
            "requested": auto_merge,
            "profile_allows": profile_allows_auto_merge,
            "eligible": not blockers,
            "method": AUTO_MERGE_METHOD,
            "blocked_by": uniq(blockers),
        },
        "required_status_checks": checks,
    }


def fetch_pr(repo: str, pr: str) -> dict[str, Any]:
    return gh_json([
        "pr",
        "view",
        pr,
        "--repo",
        parse_repo(repo),
        "--json",
        "author,files,isDraft,labels,number,title,url",
    ])


def gh_json(args: list[str]) -> Any:
    result = run(["gh", *args])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    text = result.stdout.strip()
    return json.loads(text) if text else None


def run(cmd: list[str], *, input_text: str | None = None) -> CommandResult:
    proc = subprocess.run(
        cmd,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
        cwd=ROOT,
    )
    return CommandResult(proc.returncode, proc.stdout, proc.stderr)


def command_request_reviewers(args: argparse.Namespace, policy: dict[str, Any]) -> int:
    pr = fetch_pr(args.repo, args.pr)
    author = pr["author"]["login"]
    paths = [item["path"] for item in pr.get("files") or []]
    labels = [item["name"] for item in pr.get("labels") or []]
    planned = plan(
        policy=policy,
        repo_ref=args.repo,
        author=author,
        paths=paths,
        labels=labels,
        draft=bool(pr.get("isDraft")),
        auto_merge=False,
    )
    reviewers = planned["reviewers"]
    result = {
        "plan": planned,
        "reviewer_commands": reviewer_commands(args.repo, args.pr, reviewers),
        "apply": args.apply,
    }
    if not args.apply:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    result["reviewer_results"] = apply_reviewer_requests(args.repo, str(args.pr), reviewers)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if any(item["returncode"] != 0 for item in result["reviewer_results"]) else 0


def reviewer_commands(repo: str, pr_ref: str, reviewers: list[str]) -> list[list[str]]:
    return [
        [
            "gh",
            "pr",
            "edit",
            str(pr_ref),
            "--repo",
            parse_repo(repo),
            "--add-reviewer",
            reviewer,
        ]
        for reviewer in reviewers
    ]


def apply_reviewer_requests(repo: str, pr_ref: str, reviewers: list[str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for reviewer, cmd in zip(reviewers, reviewer_commands(repo, pr_ref, reviewers)):
        gh_result = run(cmd)
        results.append(
            {
                "reviewer": reviewer,
                "returncode": gh_result.returncode,
                "stdout": gh_result.stdout.strip(),
                "stderr": gh_result.stderr.strip(),
            }
        )
    return results


def command_create(args: argparse.Namespace, policy: dict[str, Any]) -> int:
    labels = args.label or []
    paths = args.path or []
    planned = plan(
        policy=policy,
        repo_ref=args.repo,
        author=args.author,
        paths=paths,
        labels=labels,
        draft=args.draft,
        auto_merge=args.auto_merge,
    )
    body = args.body or ""
    if args.body_file:
        body = Path(args.body_file).read_text(encoding="utf-8")
    cmd = [
        "gh",
        "pr",
        "create",
        "--repo",
        parse_repo(args.repo),
        "--base",
        args.base,
        "--head",
        args.head,
        "--title",
        args.title,
        "--body",
        body,
    ]
    if args.draft:
        cmd.append("--draft")
    for label in labels:
        cmd.extend(["--label", label])

    result: dict[str, Any] = {
        "plan": planned,
        "create_command": cmd,
        "reviewer_commands": reviewer_commands(args.repo, "<created-pr>", planned["reviewers"]),
        "apply": args.apply,
    }
    if not args.apply:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    created = run(cmd)
    result["create"] = {
        "returncode": created.returncode,
        "stdout": created.stdout.strip(),
        "stderr": created.stderr.strip(),
    }
    if created.returncode != 0:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return created.returncode

    pr_ref = created.stdout.strip().splitlines()[-1]
    result["reviewer_results"] = apply_reviewer_requests(args.repo, pr_ref, planned["reviewers"])
    if planned["auto_merge"]["eligible"]:
        merge_cmd = [
            "gh",
            "pr",
            "merge",
            pr_ref,
            "--repo",
            parse_repo(args.repo),
            "--auto",
            f"--{AUTO_MERGE_METHOD}",
            "--delete-branch",
        ]
        merged = run(merge_cmd)
        result["auto_merge_command"] = merge_cmd
        result["auto_merge_result"] = {
            "returncode": merged.returncode,
            "stdout": merged.stdout.strip(),
            "stderr": merged.stderr.strip(),
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="HypeProof PR creation and review-request harness.")
    sub = parser.add_subparsers(dest="command", required=True)

    plan_parser = sub.add_parser("plan", help="Plan reviewers and auto-merge eligibility without GitHub calls.")
    plan_parser.add_argument("--repo", required=True, help="owner/name or policy repo name")
    plan_parser.add_argument("--author", required=True, help="GitHub login of PR author")
    plan_parser.add_argument("--path", action="append", default=[], help="Changed path. Can repeat.")
    plan_parser.add_argument("--label", action="append", default=[], help="PR label. Can repeat.")
    plan_parser.add_argument("--draft", action="store_true")
    plan_parser.add_argument("--auto-merge", action="store_true")

    req_parser = sub.add_parser("request-reviewers", help="Request all active members on an existing PR.")
    req_parser.add_argument("--repo", required=True)
    req_parser.add_argument("--pr", required=True)
    req_parser.add_argument("--apply", action="store_true", help="Mutate GitHub. Omit for dry-run.")

    create_parser = sub.add_parser("create", help="Create a PR with all-member reviewers.")
    create_parser.add_argument("--repo", required=True)
    create_parser.add_argument("--head", required=True)
    create_parser.add_argument("--base", default=DEFAULT_BASE)
    create_parser.add_argument("--title", required=True)
    create_parser.add_argument("--body", default="")
    create_parser.add_argument("--body-file")
    create_parser.add_argument("--author", required=True)
    create_parser.add_argument("--path", action="append", default=[])
    create_parser.add_argument("--label", action="append", default=[])
    create_parser.add_argument("--draft", action="store_true")
    create_parser.add_argument("--auto-merge", action="store_true")
    create_parser.add_argument("--apply", action="store_true", help="Mutate GitHub. Omit for dry-run.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        policy = load_policy()
        findings = validate_policy(policy)
        if findings:
            print(json.dumps({"status": "policy-invalid", "findings": [f.as_dict() for f in findings]}, indent=2))
            return 4
        if args.command == "plan":
            data = plan(
                policy=policy,
                repo_ref=args.repo,
                author=args.author,
                paths=args.path,
                labels=args.label,
                draft=args.draft,
                auto_merge=args.auto_merge,
            )
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return 0
        if args.command == "request-reviewers":
            return command_request_reviewers(args, policy)
        if args.command == "create":
            return command_create(args, policy)
    except (RuntimeError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"hype-pr: {exc}", file=sys.stderr)
        return 2
    parser.error(f"unknown command: {args.command}")
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
