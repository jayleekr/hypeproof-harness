from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "hype-review" / "review.py"
REQUEST_REVIEWERS = ROOT / "scripts" / "hype-review" / "request_reviewers.py"
SKILL = ROOT / "skills" / "hype-review" / "SKILL.md"


def run_review(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def load_module():
    spec = importlib.util.spec_from_file_location("hype_review", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["hype_review"] = module
    spec.loader.exec_module(module)
    return module


def load_request_module():
    spec = importlib.util.spec_from_file_location("hype_review_request_reviewers", REQUEST_REVIEWERS)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["hype_review_request_reviewers"] = module
    spec.loader.exec_module(module)
    return module


def test_offline_json_uses_member_lenses_and_allows_extra_role() -> None:
    proc = run_review(
        "--offline",
        "--repo",
        "jayleekr/sediment",
        "--pr",
        "87",
        "--reviewer",
        "TJ-kr",
        "--role",
        "backend",
        "--risk",
        "security",
        "--format",
        "json",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)

    assert data["roles"] == ["frontend", "product", "backend"]
    assert data["risks"] == ["security"]
    assert any(section["name"] == "frontend" for section in data["role_questions"])
    assert any(section["name"] == "product" for section in data["role_questions"])
    assert any(section["name"] == "backend" for section in data["role_questions"])
    assert any("API" in question for section in data["role_questions"] for question in section["questions"])
    assert "request_changes" in data["reply_guide"]
    assert any("Expected fix" in line for line in data["reply_guide"]["request_changes"])


def test_offline_infers_policy_lenses_for_admin_member() -> None:
    proc = run_review(
        "--offline",
        "--repo",
        "jayleekr/hypeproof-harness",
        "--pr",
        "24",
        "--reviewer",
        "JeHyeong2",
        "--format",
        "json",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)

    assert data["roles"] == ["maintainer", "backend", "security"]
    assert any(section["name"] == "maintainer" for section in data["role_questions"])
    assert any(section["name"] == "backend" for section in data["role_questions"])
    assert any(section["name"] == "security" for section in data["role_questions"])


def test_markdown_output_is_actionable_for_reviewers() -> None:
    proc = run_review(
        "--offline",
        "--repo",
        "jayleekr/hypeproof-harness",
        "--pr",
        "24",
        "--title",
        "Add hype-review",
        "--reviewer",
        "ico1036",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    assert "# hype-review" in proc.stdout
    assert "## Common Questions" in proc.stdout
    assert "## Reply Guide" in proc.stdout
    assert "### contributor" in proc.stdout
    assert "### docs" in proc.stdout
    assert "approve" in proc.stdout
    assert "request_changes" in proc.stdout


def test_path_risk_detection_covers_high_blast_radius_paths() -> None:
    module = load_module()

    risks = module.detect_risks(
        [
            ".github/workflows/deploy.yml",
            "services/sediment/auth/admin.py",
            "docs/HYPE-REVIEW.ko.md",
            "policy/repos.yaml",
            "frontend/app/page.tsx",
        ]
    )

    assert "deploy" in risks
    assert "security" in risks
    assert "docs" in risks
    assert "governance" in risks
    assert "ui" in risks


def test_member_lenses_have_fallback_when_policy_is_not_vendored() -> None:
    module = load_module()

    members = module.parse_members(ROOT / "missing-policy.yaml")

    assert members["review_lenses"]["TJ-kr"] == ["frontend", "product"]
    assert "jayleekr" in members["admins"]


def test_skill_wrapper_is_discoverable_and_uses_hype_review_script() -> None:
    content = SKILL.read_text(encoding="utf-8")
    sync = (ROOT / "scripts" / "sync.sh").read_text(encoding="utf-8")

    assert "name: hype-review" in content
    assert "user_invocable: true" in content
    assert "scripts/hype-review/review.py" in content
    assert "scripts/hype-review/request_reviewers.py" in content
    assert "hype-review" in sync.split("SKILLS=(", 1)[1].split(")", 1)[0]


def test_request_reviewers_plan_skips_author_requested_and_reviewed() -> None:
    module = load_request_module()
    pr = {
        "repository": {"nameWithOwner": "jayleekr/sediment"},
        "number": 90,
        "title": "Fix smoke",
        "url": "https://github.com/jayleekr/sediment/pull/90",
        "author": {"login": "jayleekr"},
        "reviewRequests": [{"login": "JeHyeong2"}],
        "latestReviews": [{"author": {"login": "JinyongShin"}, "state": "APPROVED"}],
        "_pendingInvites": [{"invitee": {"login": "TJ-kr"}}],
    }

    actions = module.plan_actions(
        [pr],
        ["jayleekr", "JeHyeong2", "JinyongShin", "TJ-kr"],
        apply=False,
    )
    by_reviewer = {action.reviewer: action for action in actions}

    assert by_reviewer["jayleekr"].status == "skipped"
    assert by_reviewer["jayleekr"].reason == "author"
    assert by_reviewer["JeHyeong2"].status == "skipped"
    assert by_reviewer["JeHyeong2"].reason == "already_requested"
    assert by_reviewer["JinyongShin"].status == "skipped"
    assert by_reviewer["JinyongShin"].reason == "already_reviewed"
    assert by_reviewer["TJ-kr"].status == "pending_invitation"
    assert by_reviewer["TJ-kr"].reason == "member_invitation_pending"


def test_request_reviewers_offline_json(tmp_path: Path) -> None:
    data = [
        {
            "repository": {"nameWithOwner": "jayleekr/hypeproof-harness"},
            "number": 39,
            "title": "Add merge monitor",
            "url": "https://github.com/jayleekr/hypeproof-harness/pull/39",
            "author": {"login": "jayleekr"},
            "reviewRequests": [],
            "latestReviews": [],
        }
    ]
    path = tmp_path / "prs.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            str(REQUEST_REVIEWERS),
            "--offline-file",
            str(path),
            "--member",
            "jayleekr",
            "--member",
            "ico1036",
            "--format",
            "json",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    actions = json.loads(proc.stdout)
    assert [action["status"] for action in actions] == ["skipped", "would_request"]
    assert actions[0]["reason"] == "author"
    assert actions[1]["reviewer"] == "ico1036"


# --- unrequested-approval queue (#52) -------------------------------------
# The review queue used to be built purely from `gh search --review-requested`,
# so a PR blocked on my approval whose author forgot to request me stayed
# invisible (hypeprooflab#179). These pin the gap shut.


def _pr(
    *,
    number: int = 179,
    author: str = "TJ-kr",
    repo: str = "jayleekr/hypeprooflab",
    reviews: list[dict] | None = None,
    draft: bool = False,
) -> dict:
    return {
        "repository": {"nameWithOwner": repo},
        "number": number,
        "title": "content draft",
        "url": f"https://github.com/{repo}/pull/{number}",
        "author": {"login": author},
        "labels": [],
        "latestReviews": reviews or [],
        "reviewDecision": "",
        "statusCheckRollup": [
            {"__typename": "CheckRun", "name": "build", "status": "COMPLETED", "conclusion": "SUCCESS"}
        ],
        "mergeStateStatus": "CLEAN",
        "mergeable": "MERGEABLE",
        "isDraft": draft,
        "headRefOid": "abc123",
        "autoMergeRequest": None,
        "updatedAt": "2026-07-19T00:00:00Z",
    }


def _monitor():
    module = load_module()
    return module, module._monitor_module()


def test_pr_waiting_on_my_approval_is_included_even_without_a_request() -> None:
    module, monitor = _monitor()

    assert module.needs_my_approval(_pr(), "jayleekr", monitor) is True


def test_my_own_pr_is_never_queued_for_my_approval() -> None:
    module, monitor = _monitor()

    assert module.needs_my_approval(_pr(author="jayleekr"), "jayleekr", monitor) is False


def test_pr_i_already_reviewed_is_not_requeued() -> None:
    module, monitor = _monitor()
    pr = _pr(reviews=[{"author": {"login": "jayleekr"}, "state": "APPROVED"}])

    assert module.needs_my_approval(pr, "jayleekr", monitor) is False


def test_draft_pr_is_not_queued() -> None:
    module, monitor = _monitor()

    assert module.needs_my_approval(_pr(draft=True), "jayleekr", monitor) is False


def test_at_prefixed_reviewer_is_normalized() -> None:
    module, monitor = _monitor()

    assert module.needs_my_approval(_pr(author="jayleekr"), "@jayleekr", monitor) is False


def test_merge_queues_prefers_requested_and_dedupes() -> None:
    module = load_module()
    requested = [_pr(number=179)]
    unrequested = [_pr(number=179), _pr(number=180)]

    merged = module.merge_queues(requested, unrequested)

    assert [item["number"] for item in merged] == [179, 180]
    # The surviving #179 is the requested one, so it is not marked unrequested.
    assert merged[0].get("_unrequested") is None


def test_queue_table_distinguishes_requested_from_unrequested() -> None:
    module = load_module()
    unrequested = _pr(number=180)
    unrequested["_unrequested"] = True

    lines = module.render_queue([_pr(number=179), unrequested])
    body = "\n".join(lines)

    assert "요청됨" in body
    assert "미요청(승인 대기)" in body


def test_requested_only_flag_exists_for_opting_out() -> None:
    module = load_module()
    args = module.parse_args(["--mine", "--requested-only"])

    assert args.requested_only is True
