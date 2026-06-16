#!/usr/bin/env python3
"""Enable auto-merge for PRs that are only waiting on required review."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from monitor import MergeAssessment, build_queue, fetch_open_prs, load_policy_repos


REVIEW_ONLY_BLOCKERS = {
    "human_needed_without_non_author_approval",
    "branch_review_required",
}


@dataclass(frozen=True)
class AutoMergeAction:
    repo: str
    number: int
    title: str
    url: str
    head_oid: str
    status: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "number": self.number,
            "title": self.title,
            "url": self.url,
            "headRefOid": self.head_oid,
            "status": self.status,
            "reason": self.reason,
        }


def run_gh_text(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(["gh", *args], text=True, capture_output=True, check=False)
    return proc.returncode, (proc.stderr.strip() or proc.stdout.strip())


def is_review_only_blocker(blocker: str) -> bool:
    return blocker in REVIEW_ONLY_BLOCKERS or blocker.startswith("policy_required_non_author_approvals:")


def eligible_for_auto_merge(item: MergeAssessment) -> bool:
    return (
        item.status == "waiting"
        and item.checks_ok
        and item.review_decision == "REVIEW_REQUIRED"
        and bool(item.head_oid)
        and not item.auto_merge_enabled
        and all(is_review_only_blocker(blocker) for blocker in item.blockers)
    )


def skip_reason(item: MergeAssessment) -> str:
    if item.status == "ready":
        return "ready_for_direct_merge"
    if item.status == "blocked":
        return "blocked:" + ",".join(item.blockers)
    if item.auto_merge_enabled:
        return "already_enabled"
    if not item.head_oid:
        return "missing_head_oid"
    if item.review_decision != "REVIEW_REQUIRED":
        return f"review_decision:{item.review_decision or 'none'}"
    if not all(is_review_only_blocker(blocker) for blocker in item.blockers):
        return "non_review_blockers:" + ",".join(item.blockers)
    return "not_eligible"


def plan_actions(items: list[MergeAssessment], *, apply: bool = False) -> list[AutoMergeAction]:
    actions: list[AutoMergeAction] = []
    for item in items:
        if eligible_for_auto_merge(item):
            status = "would_enable"
            reason = "waiting_for_required_review"
            if apply:
                code, detail = run_gh_text([
                    "pr",
                    "merge",
                    str(item.number),
                    "--repo",
                    item.repo,
                    "--auto",
                    "--squash",
                    "--delete-branch",
                    "--match-head-commit",
                    item.head_oid,
                ])
                status = "enabled" if code == 0 else "failed"
                if code != 0:
                    reason = detail.splitlines()[-1] if detail else "enable_auto_merge_failed"
        elif item.auto_merge_enabled:
            status = "already_enabled"
            reason = "already_enabled"
        else:
            status = "skipped"
            reason = skip_reason(item)
        actions.append(AutoMergeAction(
            repo=item.repo,
            number=item.number,
            title=item.title,
            url=item.url,
            head_oid=item.head_oid,
            status=status,
            reason=reason,
        ))
    return actions


def render_markdown(actions: list[AutoMergeAction]) -> str:
    counts = {
        status: sum(1 for action in actions if action.status == status)
        for status in ("would_enable", "enabled", "failed", "already_enabled", "skipped")
    }
    lines = [
        "# hype-merge auto-merge audit",
        "",
        (
            f"would_enable={counts['would_enable']} enabled={counts['enabled']} "
            f"failed={counts['failed']} already_enabled={counts['already_enabled']} "
            f"skipped={counts['skipped']}"
        ),
        "",
        "| Status | Repo | PR | Reason |",
        "|---|---|---:|---|",
    ]
    for action in actions:
        if action.status == "skipped":
            continue
        pr = f"[#{action.number}]({action.url})" if action.url else f"#{action.number}"
        lines.append(f"| {action.status} | `{action.repo}` | {pr} | {action.reason} |")
    if all(action.status == "skipped" for action in actions):
        lines.append("| skipped | - | - | no eligible PRs |")
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enable auto-merge for PRs only waiting on required review.")
    parser.add_argument("--repo", action="append", default=[], help="Repository in owner/name form. Defaults to policy product repos.")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--offline-file", help="JSON file containing a PR object or PR object list.")
    parser.add_argument("--apply", action="store_true", help="Mutate GitHub by enabling auto-merge.")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        if args.offline_file:
            data = json.loads(Path(args.offline_file).read_text(encoding="utf-8"))
            prs = data if isinstance(data, list) else [data]
        else:
            prs = []
            for repo in args.repo or load_policy_repos():
                prs.extend(fetch_open_prs(repo, args.limit))
        actions = plan_actions(build_queue(prs), apply=args.apply)
    except (RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"hype-merge automerge: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(json.dumps([action.as_dict() for action in actions], ensure_ascii=False, indent=2))
    else:
        print(render_markdown(actions), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
