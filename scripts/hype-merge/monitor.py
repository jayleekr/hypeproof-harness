#!/usr/bin/env python3
"""Report HypeProof PR merge readiness without mutating GitHub."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPOS = [
    "jayleekr/hypeproof-harness",
    "jayleekr/hypeproof-studio",
    "jayleekr/sediment",
    "jayleekr/hypeprooflab",
]
BLOCKING_LABELS = {"do-not-merge", "blocked", "hold"}
HUMAN_NEEDED = "human-needed"


@dataclass(frozen=True)
class MergeAssessment:
    repo: str
    number: int
    title: str
    author: str
    url: str
    status: str
    blockers: list[str]
    non_author_approvals: list[str]
    checks_ok: bool
    review_decision: str
    merge_state: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "number": self.number,
            "title": self.title,
            "author": self.author,
            "url": self.url,
            "status": self.status,
            "blockers": self.blockers,
            "non_author_approvals": self.non_author_approvals,
            "checks_ok": self.checks_ok,
            "reviewDecision": self.review_decision,
            "mergeStateStatus": self.merge_state,
        }


def run_gh(args: list[str]) -> Any:
    proc = subprocess.run(["gh", *args], text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip()
        raise RuntimeError(f"gh {' '.join(args)} failed: {detail}")
    text = proc.stdout.strip()
    return json.loads(text) if text else None


def login(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("login") or value.get("name") or "")
    return str(value or "")


def names(values: list[Any], key: str = "name") -> list[str]:
    out: list[str] = []
    for value in values or []:
        if isinstance(value, dict):
            item = value.get(key) or value.get("login")
        else:
            item = value
        if item:
            out.append(str(item))
    return out


def repo_name(pr: dict[str, Any]) -> str:
    repo = pr.get("repository")
    if isinstance(repo, dict):
        return str(repo.get("nameWithOwner") or repo.get("fullName") or repo.get("name") or "")
    return str(repo or "")


def label_names(pr: dict[str, Any]) -> list[str]:
    return names(pr.get("labels") or [])


def latest_review_state_by_author(pr: dict[str, Any]) -> dict[str, str]:
    states: dict[str, str] = {}
    for review in pr.get("latestReviews") or []:
        author = login(review.get("author") if isinstance(review, dict) else None)
        state = str(review.get("state") or "") if isinstance(review, dict) else ""
        if author and state:
            states[author] = state
    return states


def non_author_approvals(pr: dict[str, Any]) -> list[str]:
    author = login(pr.get("author")).lower()
    approvals = []
    for reviewer, state in latest_review_state_by_author(pr).items():
        if reviewer.lower() != author and state == "APPROVED":
            approvals.append(reviewer)
    return sorted(approvals, key=str.lower)


def changes_requested(pr: dict[str, Any]) -> list[str]:
    return sorted(
        reviewer
        for reviewer, state in latest_review_state_by_author(pr).items()
        if state == "CHANGES_REQUESTED"
    )


def rollup_checks_ok(pr: dict[str, Any]) -> bool:
    rollup = pr.get("statusCheckRollup") or []
    for check in rollup:
        if not isinstance(check, dict):
            continue
        typename = check.get("__typename")
        if typename == "CheckRun" or "conclusion" in check:
            if check.get("status") != "COMPLETED":
                return False
            if check.get("conclusion") not in ("SUCCESS", "SKIPPED", "NEUTRAL"):
                return False
            continue
        if typename == "StatusContext" or "state" in check:
            if check.get("state") != "SUCCESS":
                return False
    return True


def classify_pr(pr: dict[str, Any], *, required_non_author_approvals: int = 0) -> MergeAssessment:
    labels = label_names(pr)
    review_decision = str(pr.get("reviewDecision") or "")
    merge_state = str(pr.get("mergeStateStatus") or "")
    mergeable = str(pr.get("mergeable") or "")
    approvals = non_author_approvals(pr)
    requested_changes = changes_requested(pr)
    checks_ok = rollup_checks_ok(pr)
    blockers: list[str] = []

    if pr.get("isDraft"):
        blockers.append("draft")
    if mergeable and mergeable != "MERGEABLE":
        blockers.append(f"mergeable:{mergeable}")
    if merge_state and merge_state not in ("CLEAN", "HAS_HOOKS", "BLOCKED"):
        blockers.append(f"merge_state:{merge_state}")
    if not checks_ok:
        blockers.append("checks_pending_or_failed")
    for label in labels:
        if label in BLOCKING_LABELS:
            blockers.append(f"label:{label}")
    for reviewer in requested_changes:
        blockers.append(f"changes_requested:{reviewer}")

    if HUMAN_NEEDED in labels and not approvals:
        blockers.append("human_needed_without_non_author_approval")
    if required_non_author_approvals and len(approvals) < required_non_author_approvals:
        if HUMAN_NEEDED not in labels or approvals:
            blockers.append(f"policy_required_non_author_approvals:{len(approvals)}/{required_non_author_approvals}")
    if review_decision == "REVIEW_REQUIRED":
        blockers.append("branch_review_required")
    elif review_decision == "CHANGES_REQUESTED":
        blockers.append("branch_changes_requested")
    elif review_decision and review_decision != "APPROVED":
        blockers.append(f"review_decision:{review_decision}")

    status = "ready"
    if blockers:
        review_only = {
            "human_needed_without_non_author_approval",
            "branch_review_required",
        }
        status = "waiting" if all(
            blocker in review_only or blocker.startswith("policy_required_non_author_approvals:")
            for blocker in blockers
        ) else "blocked"

    return MergeAssessment(
        repo=repo_name(pr),
        number=int(pr.get("number") or 0),
        title=str(pr.get("title") or ""),
        author=login(pr.get("author")),
        url=str(pr.get("url") or ""),
        status=status,
        blockers=blockers,
        non_author_approvals=approvals,
        checks_ok=checks_ok,
        review_decision=review_decision,
        merge_state=merge_state,
    )


def load_policy_scope() -> tuple[list[str], dict[str, int]]:
    try:
        import yaml  # type: ignore
    except ImportError:
        return DEFAULT_REPOS, {}

    path = ROOT / "policy" / "repos.yaml"
    if not path.exists():
        return DEFAULT_REPOS, {}
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    profiles: dict[str, dict[str, Any]] = {}
    for profile_path in sorted((ROOT / "policy" / "profiles").glob("*.yaml")):
        profile = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
        if profile.get("profile"):
            profiles[str(profile["profile"])] = profile

    repos = []
    required_approvals: dict[str, int] = {}
    for item in doc.get("repositories", []):
        owner = item.get("owner")
        name = item.get("name")
        if owner and name and item.get("lifecycle") != "release":
            full = f"{owner}/{name}"
            repos.append(full)
            profile = profiles.get(str(item.get("profile") or ""), {})
            reviews = (
                profile.get("branch_protection", {})
                .get("required_pull_request_reviews", {})
            )
            count = int(reviews.get("required_approving_review_count") or 0)
            if count > 0:
                required_approvals[full] = count
    return repos or DEFAULT_REPOS, required_approvals


def load_policy_repos() -> list[str]:
    repos, _required_approvals = load_policy_scope()
    return repos


def load_policy_review_requirements() -> dict[str, int]:
    _repos, required_approvals = load_policy_scope()
    return required_approvals


def fetch_open_prs(repo: str, limit: int) -> list[dict[str, Any]]:
    listed = run_gh([
        "pr",
        "list",
        "--repo",
        repo,
        "--state",
        "open",
        "--limit",
        str(limit),
        "--json",
        "number",
    ]) or []
    prs = []
    fields = (
        "author,headRefOid,isDraft,labels,latestReviews,mergeStateStatus,"
        "mergeable,number,reviewDecision,reviewRequests,"
        "statusCheckRollup,title,updatedAt,url"
    )
    for item in listed:
        pr = run_gh(["pr", "view", str(item["number"]), "--repo", repo, "--json", fields])
        pr["repository"] = {"nameWithOwner": repo}
        prs.append(pr)
    return prs


def build_queue(prs: list[dict[str, Any]]) -> list[MergeAssessment]:
    repo_order = {repo: index for index, repo in enumerate(load_policy_repos())}
    review_requirements = load_policy_review_requirements()
    assessed = [
        classify_pr(pr, required_non_author_approvals=review_requirements.get(repo_name(pr), 0))
        for pr in prs
    ]
    return sorted(
        assessed,
        key=lambda item: (
            {"ready": 0, "waiting": 1, "blocked": 2}.get(item.status, 9),
            repo_order.get(item.repo, 999),
            item.number,
        ),
    )


def render_markdown(items: list[MergeAssessment]) -> str:
    counts = {status: sum(1 for item in items if item.status == status) for status in ("ready", "waiting", "blocked")}
    lines = [
        "# hype-merge monitor",
        "",
        f"ready={counts['ready']} waiting={counts['waiting']} blocked={counts['blocked']}",
        "",
        "| Status | Repo | PR | Author | Checks | Non-author approvals | Blockers |",
        "|---|---|---:|---|---|---|---|",
    ]
    for item in items:
        pr = f"[#{item.number}]({item.url})" if item.url else f"#{item.number}"
        blockers = ", ".join(item.blockers) if item.blockers else "-"
        approvals = ", ".join(f"@{name}" for name in item.non_author_approvals) or "-"
        checks = "ok" if item.checks_ok else "not-ok"
        lines.append(f"| {item.status} | `{item.repo}` | {pr} | @{item.author} | {checks} | {approvals} | {blockers} |")
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report HypeProof PR merge readiness.")
    parser.add_argument("--repo", action="append", default=[], help="Repository in owner/name form. Defaults to policy product repos.")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--offline-file", help="JSON file containing a PR object or PR object list.")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        if args.offline_file:
            data = json.loads(Path(args.offline_file).read_text(encoding="utf-8"))
            prs = data if isinstance(data, list) else [data]
        else:
            repos = args.repo or load_policy_repos()
            prs = []
            for repo in repos:
                prs.extend(fetch_open_prs(repo, args.limit))
        queue = build_queue(prs)
    except (RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"hype-merge: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(json.dumps([item.as_dict() for item in queue], ensure_ascii=False, indent=2))
    else:
        print(render_markdown(queue), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
