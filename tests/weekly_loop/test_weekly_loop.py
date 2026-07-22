from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "scripts" / "weekly-harness" / "check.py"
BURNDOWN = ROOT / "scripts" / "weekly-harness" / "burndown.py"
SKILL = ROOT / "skills" / "weekly-loop" / "SKILL.md"
DOC = ROOT / "docs" / "WEEKLY-LOOP.ko.md"

CYCLE = "weekly-2026-07-21"
REPO = "jayleekr/sediment"

GOOD_BODY = (
    "## Context\n\n회의록 요약.\n\n## Tasks\n\n- [ ] 작업 1\n\n"
    "## Owner\n\n담당: @TJ-kr\n\n## ETA\n\nETA: 2026-07-20\n"
)


def run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def fixture(tmp_path: Path, issues: list[dict]) -> str:
    path = tmp_path / "issues.json"
    path.write_text(json.dumps({REPO: issues}), encoding="utf-8")
    return str(path)


def test_check_passes_when_owner_and_eta_are_present_and_on_time(tmp_path: Path) -> None:
    fx = fixture(tmp_path, [{"number": 1, "title": "Do the thing", "body": GOOD_BODY}])
    proc = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "OK" in proc.stdout
    assert "VIOLATION" not in proc.stdout


def test_check_fails_on_missing_eta_missing_owner_and_late_eta(tmp_path: Path) -> None:
    fx = fixture(
        tmp_path,
        [
            {"number": 2, "title": "No ETA", "body": "## Owner\n\n담당: @jayleekr\n"},
            {"number": 3, "title": "No owner", "body": "ETA: 2026-07-21\n"},
            {"number": 4, "title": "Late", "body": "## Owner\n\nOwner: @jayleekr\n\nETA: 2026-07-25\n"},
        ],
    )
    proc = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "missing 'ETA:' line" in proc.stdout
    assert "missing 'Owner'/담당 section" in proc.stdout
    assert "after the cycle date" in proc.stdout
    assert "3 violation(s)" in proc.stdout


def test_check_rejects_malformed_cycle_label() -> None:
    proc = run(CHECK, "--cycle", "weekly-21-07-2026")
    assert proc.returncode == 2
    assert "bad cycle label" in proc.stderr


def test_check_accepts_korean_owner_section_and_bold_eta(tmp_path: Path) -> None:
    body = "### 담당\n\n@JinyongShin\n\n**ETA**: 2026-07-21\n"
    fx = fixture(tmp_path, [{"number": 5, "title": "Korean sections", "body": body}])
    proc = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_check_accepts_bold_eta_value(tmp_path: Path) -> None:
    body = "## Owner\n\n담당: @jayleekr\n\nETA: **2026-07-20**\n"
    fx = fixture(tmp_path, [{"number": 6, "title": "Bold ETA value", "body": body}])
    proc = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "unparseable" not in proc.stdout


def test_check_accepts_eta_heading_with_date_on_next_line(tmp_path: Path) -> None:
    # issues filed before the inline 'ETA:' template existed (2026-07-14 fanout)
    body = "## Owner\nJay (이재원)\n\n## ETA\n2026-07-17 — 두 파이프라인 재기동 완료\n"
    fx = fixture(tmp_path, [{"number": 7, "title": "Heading-style ETA", "body": body}])
    proc = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_check_rejects_heading_that_merely_contains_owner(tmp_path: Path) -> None:
    body = "## Ownership review\n\nnobody in particular\n\nETA: 2026-07-20\n"
    fx = fixture(tmp_path, [{"number": 7, "title": "Fake owner heading", "body": body}])
    proc = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "missing 'Owner'/담당 section" in proc.stdout


# ---- evidence completion gate (WEEKLY-LOOP §2 원칙 4) ----
# A closed cycle issue must reference evidence or carry an explicit exemption.

PR_URL = "https://github.com/jayleekr/sediment/pull/42"


def closed(number: int, title: str, **extra: object) -> dict:
    return {"number": number, "title": title, "state": "CLOSED", "body": "", **extra}


def test_evidence_gate_accepts_valid_ref_in_a_closing_comment(tmp_path: Path) -> None:
    fx = fixture(
        tmp_path,
        [closed(10, "Shipped", comments=[{"body": f"완료.\n\nEvidence: {PR_URL}\n"}])],
    )
    proc = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "OK" in proc.stdout
    assert "VIOLATION" not in proc.stdout


def test_evidence_gate_rejects_closed_issue_with_no_ref(tmp_path: Path) -> None:
    fx = fixture(tmp_path, [closed(11, "Silently closed", body="다 했음.")])
    proc = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "closed with no 'Evidence:' ref" in proc.stdout
    assert "1 violation(s)" in proc.stdout


def test_evidence_gate_rejects_malformed_ref(tmp_path: Path) -> None:
    fx = fixture(
        tmp_path,
        [
            closed(12, "Prose instead of a link", body="Evidence: 슬랙에 공유함"),
            closed(13, "Wrong host", body="Evidence: https://example.com/report.pdf"),
            closed(14, "Repo root, not a permalink", body="Evidence: https://github.com/a/b"),
        ],
    )
    proc = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "malformed Evidence ref" in proc.stdout
    assert "3 violation(s)" in proc.stdout


def test_evidence_gate_exempts_labelled_non_deliverable(tmp_path: Path) -> None:
    fx = fixture(
        tmp_path,
        [closed(15, "Rename the Discord channel", labels=[{"name": "no-evidence-needed"}])],
    )
    proc = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "EXEMPT" in proc.stdout
    assert "1 exempt" in proc.stdout


def test_evidence_gate_exempts_issue_closed_as_not_planned(tmp_path: Path) -> None:
    fx = fixture(tmp_path, [closed(16, "Dropped in the meeting", stateReason="NOT_PLANNED")])
    proc = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "not planned" in proc.stdout


def test_evidence_gate_is_not_satisfied_by_an_unmarked_link(tmp_path: Path) -> None:
    # anti-fabrication: pasting a PR link without the 'Evidence:' marker is
    # something ordinary issue bodies do all the time and must not pass.
    fx = fixture(tmp_path, [closed(17, "Chatty body", body=f"관련 PR: {PR_URL}\n")])
    proc = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "closed with no 'Evidence:' ref" in proc.stdout


def test_evidence_gate_accepts_commit_and_comment_permalinks(tmp_path: Path) -> None:
    fx = fixture(
        tmp_path,
        [
            closed(18, "Commit ref", body="Evidence: https://github.com/jayleekr/sediment/commit/"
                                          "9f2c1ab4d5e6f708192a3b4c5d6e7f8091a2b3c4"),
            closed(19, "Comment ref", body="증거: https://github.com/jayleekr/hypeprooflab/"
                                           "issues/7#issuecomment-3120044556"),
        ],
    )
    proc = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "0 violation(s)" in proc.stdout


def test_evidence_gate_does_not_impose_owner_eta_on_closed_issues(tmp_path: Path) -> None:
    # regression guard: the Owner/ETA rule stays scoped to OPEN issues.
    fx = fixture(tmp_path, [closed(20, "No owner, no ETA", body=f"Evidence: {PR_URL}")])
    proc = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "missing 'Owner'" not in proc.stdout
    assert "missing 'ETA:'" not in proc.stdout


def test_skip_evidence_gate_flag_bypasses_closed_issue_checks(tmp_path: Path) -> None:
    fx = fixture(tmp_path, [closed(21, "No evidence at all", body="끝.")])
    proc = run(
        CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx, "--skip-evidence-gate"
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "SKIP" in proc.stdout


def test_check_still_enforces_owner_eta_on_open_issues_alongside_closed(tmp_path: Path) -> None:
    fx = fixture(
        tmp_path,
        [
            {"number": 22, "title": "Open and clean", "body": GOOD_BODY, "state": "OPEN"},
            {"number": 23, "title": "Open and late", "body": "Owner: @jayleekr\nETA: 2026-08-01"},
            closed(24, "Closed with evidence", body=f"Evidence: {PR_URL}"),
            closed(25, "Closed without evidence"),
        ],
    )
    proc = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "after the cycle date" in proc.stdout
    assert "closed with no 'Evidence:' ref" in proc.stdout
    assert "2 violation(s)" in proc.stdout


def test_burndown_reports_closed_vs_open_with_owner_and_state(tmp_path: Path) -> None:
    fx = fixture(
        tmp_path,
        [
            {"number": 1, "title": "Shipped", "body": GOOD_BODY, "state": "CLOSED", "url": "u1"},
            {
                "number": 2,
                "title": "Still open | pipes",
                "body": "no owner line",
                "state": "OPEN",
                "assignees": [{"login": "TJ-kr"}],
                "url": "u2",
            },
        ],
    )
    proc = run(BURNDOWN, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert f"# Weekly burndown — {CYCLE}" in proc.stdout
    assert f"## {REPO} — closed 1 / open 1" in proc.stdout
    assert "| # | Title | Owner | State |" in proc.stdout
    assert "@TJ-kr" in proc.stdout          # assignee fallback for the open issue
    assert "Still open \\| pipes" in proc.stdout  # pipe escaping
    assert "CLOSED" in proc.stdout and "OPEN" in proc.stdout


def test_burndown_rejects_malformed_cycle_label() -> None:
    proc = run(BURNDOWN, "--cycle", "sprint-1")
    assert proc.returncode == 2
    assert "bad cycle label" in proc.stderr


def test_skill_and_doc_are_registered_in_sync_arrays() -> None:
    sync = (ROOT / "scripts" / "sync.sh").read_text(encoding="utf-8")
    skill = SKILL.read_text(encoding="utf-8")
    doc = DOC.read_text(encoding="utf-8")

    assert "name: weekly-loop" in skill
    assert "scripts/weekly-harness/check.py" in skill
    assert "scripts/weekly-harness/burndown.py" in skill
    assert "hypeproof-harness:docs/WEEKLY-LOOP.ko.md" in doc
    assert "weekly-loop" in sync.split("SKILLS=(", 1)[1].split(")", 1)[0]
    assert "WEEKLY-LOOP.ko.md" in sync.split("DOCS=(", 1)[1].split(")", 1)[0]
    assert "weekly-harness" in sync.split("SCRIPTS=(", 1)[1].split(")", 1)[0]
