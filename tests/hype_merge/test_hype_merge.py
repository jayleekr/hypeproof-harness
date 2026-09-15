from __future__ import annotations

import importlib.util
import builtins
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


def test_policy_loading_fails_closed_without_pyyaml(monkeypatch) -> None:
    module = load_module()
    original_import = builtins.__import__

    def without_yaml(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("synthetic missing dependency")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_yaml)
    try:
        module.load_policy_scope()
    except RuntimeError as exc:
        assert "refusing to drop canonical merge policy" in str(exc)
    else:
        raise AssertionError("missing PyYAML must not weaken approval policy")


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


def test_fetch_open_prs_uses_one_complete_list_query(monkeypatch) -> None:
    module = load_module()
    calls: list[list[str]] = []

    def fake_run_gh(args: list[str]):
        calls.append(args)
        return [pr()]

    monkeypatch.setattr(module, "run_gh", fake_run_gh)
    items = module.fetch_open_prs("jayleekr/hypeproof-studio", 100)

    assert len(calls) == 1
    assert calls[0][:2] == ["pr", "list"]
    fields = calls[0][calls[0].index("--json") + 1]
    assert "statusCheckRollup" in fields
    assert "latestReviews" in fields
    assert items[0]["repository"]["nameWithOwner"] == "jayleekr/hypeproof-studio"


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


def test_merge_ready_apply_uses_exact_head_without_auto(monkeypatch) -> None:
    automerge = load_automerge()
    ready = pr(
        author="JinyongShin",
        reviews=[review("jayleekr", "APPROVED")],
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(
        automerge,
        "run_gh_text",
        lambda args: (calls.append(args) or 0, "f" * 40 if args[:2] == ["pr", "view"] else "merged"),
    )

    actions = automerge.plan_actions(
        automerge.build_queue([ready]), apply=True, merge_ready=True
    )

    assert actions[0].status == "merged"
    assert "--auto" not in calls[0]
    assert "--match-head-commit" in calls[0]
    assert "abc123" in calls[0]
    # The merge commit is confirmed and reported so follow-up has an exact revert unit.
    assert calls[1][:2] == ["pr", "view"]
    assert actions[0].merge_commit == "f" * 40
    assert actions[0].reason == "merge_commit:" + "f" * 40


def ready_pr(repo: str, number: int) -> dict:
    item = pr(author="JinyongShin", reviews=[review("jayleekr", "APPROVED")])
    item["repository"] = {"nameWithOwner": repo}
    item["number"] = number
    return item


def record_gh(monkeypatch, automerge, result=(0, "merged")) -> list[list[str]]:
    calls: list[list[str]] = []
    monkeypatch.setattr(automerge, "run_gh_text", lambda args: (calls.append(args), result)[1])
    return calls


def test_merge_ready_offline_file_cannot_merge_multiple_repositories(tmp_path: Path, monkeypatch) -> None:
    # Review blocker on #165: --offline-file used to skip the single repo/PR guard entirely.
    automerge = load_automerge()
    data = tmp_path / "two-ready.json"
    data.write_text(json.dumps([
        ready_pr("jayleekr/hypeproof-studio", 901),
        ready_pr("jayleekr/hypeproof-harness", 902),
    ]), encoding="utf-8")
    calls = record_gh(monkeypatch, automerge)

    assert automerge.main(["--offline-file", str(data), "--merge-ready", "--apply"]) == 2
    assert automerge.main(["--offline-file", str(data), "--merge-ready", "--apply",
                           "--repo", "jayleekr/hypeproof-studio"]) == 2
    assert calls == []

    # Positive control: the same file with one selected repo/PR merges exactly that PR.
    record = record_gh(monkeypatch, automerge)
    assert automerge.main(["--offline-file", str(data), "--merge-ready", "--apply",
                           "--repo", "jayleekr/hypeproof-studio", "--pr", "901"]) == 0
    merges = [c for c in record if c[:2] == ["pr", "merge"]]
    assert len(merges) == 1 and merges[0][2] == "901"


def test_merge_ready_refuses_profile_without_machine_merge(tmp_path: Path, monkeypatch) -> None:
    automerge = load_automerge()
    module = load_module()
    assert "jayleekr/hypeprooflab" not in module.load_auto_merge_policy_repos()
    data = tmp_path / "lab.json"
    data.write_text(json.dumps([ready_pr("jayleekr/hypeprooflab", 119)]), encoding="utf-8")
    calls = record_gh(monkeypatch, automerge)

    assert automerge.main(["--offline-file", str(data), "--merge-ready", "--apply",
                           "--repo", "jayleekr/hypeprooflab", "--pr", "119"]) == 2
    assert calls == []


def test_merge_ready_never_merges_blocked_or_unconfirmed_prs(monkeypatch) -> None:
    automerge = load_automerge()
    failing = ready_pr("jayleekr/hypeproof-studio", 1)
    failing["statusCheckRollup"] = [check("build", conclusion="FAILURE")]
    conflicting = ready_pr("jayleekr/hypeproof-studio", 2)
    conflicting["mergeable"] = "CONFLICTING"
    platform_blocked = ready_pr("jayleekr/hypeproof-studio", 3)
    platform_blocked["mergeStateStatus"] = "BLOCKED"
    unknown = ready_pr("jayleekr/hypeproof-studio", 4)
    unknown["mergeStateStatus"] = ""
    held = ready_pr("jayleekr/hypeproof-studio", 5)
    held["labels"] = [{"name": "hold"}]
    calls = record_gh(monkeypatch, automerge)

    actions = automerge.plan_actions(
        automerge.build_queue([failing, conflicting, platform_blocked, unknown, held]),
        apply=True, merge_ready=True,
    )

    assert calls == []
    assert {a.number: a.status for a in actions} == {1: "skipped", 2: "skipped", 3: "skipped", 4: "skipped", 5: "skipped"}
    assert {a.number: a.reason for a in actions}[3] == "merge_state_not_clean:BLOCKED"
    assert {a.number: a.reason for a in actions}[4] == "merge_state_not_clean:unknown"


def test_merge_ready_reports_merge_failure_and_unconfirmed_commit(monkeypatch) -> None:
    automerge = load_automerge()
    queue = automerge.build_queue([ready_pr("jayleekr/hypeproof-studio", 7)])

    record_gh(monkeypatch, automerge, (1, "GraphQL: Head branch was modified"))
    failed = automerge.plan_actions(queue, apply=True, merge_ready=True)
    assert failed[0].status == "failed"
    assert "Head branch was modified" in failed[0].reason
    assert failed[0].merge_commit == ""

    record_gh(monkeypatch, automerge, (0, ""))
    unconfirmed = automerge.plan_actions(queue, apply=True, merge_ready=True)
    assert unconfirmed[0].status == "merged"
    assert unconfirmed[0].reason == "merge_commit_unconfirmed"


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
