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


def test_check_rejects_heading_that_merely_contains_owner(tmp_path: Path) -> None:
    body = "## Ownership review\n\nnobody in particular\n\nETA: 2026-07-20\n"
    fx = fixture(tmp_path, [{"number": 7, "title": "Fake owner heading", "body": body}])
    proc = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "missing 'Owner'/담당 section" in proc.stdout


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
