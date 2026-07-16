from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "hype-merge" / "monitor.py"
AUTOMERGE = ROOT / "scripts" / "hype-merge" / "automerge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("hype_merge", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["hype_merge"] = module
    spec.loader.exec_module(module)
    return module


def load_automerge():
    # automerge.py does `from monitor import ...`, so its directory must be importable.
    sys.path.insert(0, str(AUTOMERGE.parent))
    spec = importlib.util.spec_from_file_location("hype_automerge", AUTOMERGE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["hype_automerge"] = module
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
        "headRefOid": "abc123",
        "autoMergeRequest": None,
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
    assert items[0]["autoMergeEnabled"] is False


def test_policy_repos_exclude_release_and_retired_repositories() -> None:
    module = load_module()
    repos = module.load_policy_repos()

    assert "jayleekr/sediment-cli-releases" not in repos
    assert "jayleekr/Claude-Code-Remote" not in repos


def test_auto_merge_policy_repos_respect_profile_allow_auto_merge() -> None:
    module = load_module()
    repos = module.load_auto_merge_policy_repos()

    assert "jayleekr/hypeproof-harness" in repos
    assert "jayleekr/sediment" in repos
    assert "jayleekr/jayleekr.github.io" not in repos


def test_automerge_dry_run_targets_review_only_waiting_prs(tmp_path: Path) -> None:
    waiting = pr(labels=["human-needed"], review_decision="REVIEW_REQUIRED")
    waiting["number"] = 39
    blocked = pr(
        labels=["human-needed"],
        review_decision="REVIEW_REQUIRED",
        checks=[check("build", conclusion="FAILURE")],
    )
    blocked["number"] = 40
    data = tmp_path / "prs.json"
    data.write_text(json.dumps([blocked, waiting]), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(AUTOMERGE), "--offline-file", str(data), "--format", "json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    actions = json.loads(proc.stdout)
    by_number = {item["number"]: item for item in actions}
    assert by_number[39]["status"] == "would_enable"
    assert by_number[39]["reason"] == "waiting_for_required_review"
    assert by_number[40]["status"] == "skipped"
    assert by_number[40]["reason"].startswith("blocked:")


def test_automerge_dry_run_reports_already_enabled(tmp_path: Path) -> None:
    waiting = pr(labels=["human-needed"], review_decision="REVIEW_REQUIRED")
    waiting["number"] = 39
    waiting["autoMergeRequest"] = {"enabledAt": "2026-06-16T16:12:48Z"}
    data = tmp_path / "prs.json"
    data.write_text(json.dumps([waiting]), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(AUTOMERGE), "--offline-file", str(data), "--format", "json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    actions = json.loads(proc.stdout)
    assert actions[0]["status"] == "already_enabled"
    assert actions[0]["reason"] == "already_enabled"


def test_rollup_checks_ok_treats_empty_rollup_as_not_ok() -> None:
    module = load_module()

    # An empty / missing rollup carries no green signal — must be not-ok.
    assert module.rollup_checks_ok({}) is False
    assert module.rollup_checks_ok({"statusCheckRollup": []}) is False

    item = module.classify_pr(pr(checks=[]))
    assert item.checks_ok is False
    assert "checks_pending_or_failed" in item.blockers
    assert item.status == "blocked"


def test_automerge_apply_enables_and_reports_failure(monkeypatch) -> None:
    automerge = load_automerge()

    waiting = pr(labels=["human-needed"], review_decision="REVIEW_REQUIRED")
    waiting["number"] = 39

    calls: list[list[str]] = []

    def fake_gh_ok(args: list[str]) -> tuple[int, str]:
        calls.append(args)
        return 0, "enabled auto-merge"

    monkeypatch.setattr(automerge, "run_gh_text", fake_gh_ok)
    actions = automerge.plan_actions(automerge.build_queue([waiting]), apply=True)

    assert actions[0].status == "enabled"
    # The mutation is a native auto-merge pinned to the reviewed head commit.
    assert calls[0][:3] == ["pr", "merge", "39"]
    assert "--auto" in calls[0]
    assert "--squash" in calls[0]
    assert "--match-head-commit" in calls[0]
    assert "abc123" in calls[0]

    # Failure path surfaces status=failed and the gh error as the reason.
    monkeypatch.setattr(automerge, "run_gh_text", lambda args: (1, "gh: merge blocked"))
    failed = automerge.plan_actions(automerge.build_queue([waiting]), apply=True)
    assert failed[0].status == "failed"
    assert "merge blocked" in failed[0].reason


def test_monitor_markdown_shows_auto_merge_status(tmp_path: Path) -> None:
    waiting = pr(labels=["human-needed"], review_decision="REVIEW_REQUIRED")
    waiting["autoMergeRequest"] = {"enabledAt": "2026-06-16T16:12:48Z"}
    data = tmp_path / "prs.json"
    data.write_text(json.dumps([waiting]), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--offline-file", str(data)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "| Status | Repo | PR | Author | Checks | Auto-merge |" in proc.stdout
    assert "| waiting | `jayleekr/hypeprooflab` | [#119]" in proc.stdout
    assert " | ok | enabled | " in proc.stdout
