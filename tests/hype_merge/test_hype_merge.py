from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "hype-merge" / "monitor.py"


def load_module():
    spec = importlib.util.spec_from_file_location("hype_merge", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["hype_merge"] = module
    spec.loader.exec_module(module)
    return module


def check(name: str, status: str = "COMPLETED", conclusion: str = "SUCCESS") -> dict:
    return {
        "__typename": "CheckRun",
        "name": name,
        "status": status,
        "conclusion": conclusion,
    }


def pr(
    *,
    author: str = "jayleekr",
    labels: list[str] | None = None,
    reviews: list[dict] | None = None,
    review_decision: str = "",
    checks: list[dict] | None = None,
    mergeable: str = "MERGEABLE",
    is_draft: bool = False,
) -> dict:
    return {
        "repository": {"nameWithOwner": "jayleekr/hypeprooflab"},
        "number": 119,
        "title": "Deploy docs",
        "author": {"login": author},
        "url": "https://github.com/jayleekr/hypeprooflab/pull/119",
        "labels": [{"name": label} for label in (labels or [])],
        "latestReviews": reviews or [],
        "reviewDecision": review_decision,
        "statusCheckRollup": checks if checks is not None else [check("build")],
        "mergeStateStatus": "CLEAN",
        "mergeable": mergeable,
        "isDraft": is_draft,
    }


def review(author: str, state: str) -> dict:
    return {"author": {"login": author}, "state": state}


def test_human_needed_requires_non_author_approval_even_without_branch_rule() -> None:
    module = load_module()

    item = module.classify_pr(pr(labels=["human-needed"], review_decision=""))

    assert item.status == "waiting"
    assert "human_needed_without_non_author_approval" in item.blockers


def test_non_author_approval_can_make_no_branch_rule_pr_ready() -> None:
    module = load_module()

    item = module.classify_pr(
        pr(
            labels=["human-needed"],
            reviews=[review("JeHyeong2", "APPROVED")],
            review_decision="",
        )
    )

    assert item.status == "ready"
    assert item.blockers == []
    assert item.non_author_approvals == ["JeHyeong2"]


def test_self_approval_does_not_satisfy_human_needed() -> None:
    module = load_module()

    item = module.classify_pr(
        pr(
            labels=["human-needed"],
            reviews=[review("jayleekr", "APPROVED")],
            review_decision="",
        )
    )

    assert item.status == "waiting"
    assert item.non_author_approvals == []
    assert "human_needed_without_non_author_approval" in item.blockers


def test_branch_review_required_stays_waiting_after_one_approval() -> None:
    module = load_module()

    item = module.classify_pr(
        pr(
            labels=["human-needed"],
            reviews=[review("JeHyeong2", "APPROVED")],
            review_decision="REVIEW_REQUIRED",
        )
    )

    assert item.status == "waiting"
    assert item.non_author_approvals == ["JeHyeong2"]
    assert "branch_review_required" in item.blockers


def test_policy_profile_requires_non_author_approval_without_label() -> None:
    module = load_module()

    items = module.build_queue([pr(labels=[], review_decision="")])

    assert items[0].status == "waiting"
    assert "policy_required_non_author_approvals:0/1" in items[0].blockers


def test_policy_profile_required_approval_count_can_exceed_one() -> None:
    module = load_module()
    item = pr(
        author="JinyongShin",
        labels=[],
        reviews=[review("jayleekr", "APPROVED")],
        review_decision="",
    )
    item["repository"] = {"nameWithOwner": "jayleekr/hypeproof-harness"}

    items = module.build_queue([item])

    assert items[0].status == "waiting"
    assert "policy_required_non_author_approvals:1/2" in items[0].blockers


def test_changes_requested_and_failed_checks_are_blocked() -> None:
    module = load_module()

    item = module.classify_pr(
        pr(
            labels=["human-needed"],
            reviews=[review("JeHyeong2", "APPROVED"), review("TJ-kr", "CHANGES_REQUESTED")],
            review_decision="CHANGES_REQUESTED",
            checks=[check("build", conclusion="FAILURE")],
        )
    )

    assert item.status == "blocked"
    assert "changes_requested:TJ-kr" in item.blockers
    assert "checks_pending_or_failed" in item.blockers
    assert "branch_changes_requested" in item.blockers


def test_success_conclusion_beats_stale_in_progress_check_status() -> None:
    module = load_module()

    item = module.classify_pr(
        pr(
            labels=["human-needed"],
            reviews=[review("JeHyeong2", "APPROVED")],
            review_decision="",
            checks=[check("gate", status="IN_PROGRESS", conclusion="SUCCESS")],
        )
    )

    assert item.checks_ok is True
    assert "checks_pending_or_failed" not in item.blockers


def test_offline_file_json_renders_ready_first(tmp_path: Path) -> None:
    waiting = pr(labels=["human-needed"])
    ready = pr(
        author="JinyongShin",
        labels=["human-needed"],
        reviews=[review("jayleekr", "APPROVED")],
        review_decision="",
    )
    ready["number"] = 263
    ready["repository"] = {"nameWithOwner": "jayleekr/hypeproof-studio"}
    data = tmp_path / "prs.json"
    data.write_text(json.dumps([waiting, ready]), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--offline-file", str(data), "--format", "json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    items = json.loads(proc.stdout)
    assert [item["status"] for item in items] == ["ready", "waiting"]
    assert items[0]["number"] == 263
