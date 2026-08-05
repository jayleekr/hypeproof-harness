from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "studio-quality-dashboard" / "dashboard.py"
HTML = ROOT / "docs" / "studio-quality-dashboard.html"


def run_dashboard(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_init_creates_cohort_source_of_truth(tmp_path: Path) -> None:
    out = tmp_path / "cohort.json"
    proc = run_dashboard(
        "init",
        "--course",
        "SK 바이오팜 AI 게임 창작 워크숍",
        "--date",
        "2026-08-17",
        "--slug",
        "sk-biopharm-2026-08-17",
        "--output",
        str(out),
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["title"] == "hypeproof studio quality dash board"
    assert data["ready_page"].endswith("/ready/sk-biopharm-2026-08-17")
    assert [gate["id"] for gate in data["gates"]] == ["G1", "G2", "G3"]
    assert data["gates"][0]["due"] == "2026-08-07"
    assert data["gates"][1]["due"] == "2026-08-10"
    assert data["gates"][2]["due"] == "2026-08-12"
    assert [report["accepts_upload"] for report in data["reports"]] == [True, True, True, False]
    assert all(report["uploaded"] is None for report in data["reports"])


def test_issue_plan_contains_course_date_prefix_and_evidence(tmp_path: Path) -> None:
    cohort = tmp_path / "cohort.json"
    run_dashboard(
        "init",
        "--course",
        "SK 바이오팜 AI 게임 창작 워크숍",
        "--date",
        "2026-08-17",
        "--slug",
        "sk-biopharm-2026-08-17",
        "--output",
        str(cohort),
    )
    proc = run_dashboard("plan-issues", str(cohort), "--json")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    issues = json.loads(proc.stdout)
    assert len(issues) == 3
    assert issues[0]["title"].startswith("SK 바이오팜 AI 게임 창작 워크숍 - 2026-08-17 - G1")
    assert "Evidence: <보고서/PR/코멘트 permalink>" in issues[0]["body"]
    assert "cohort:sk-biopharm-2026-08-17" in issues[0]["labels"]


def test_create_issues_is_dry_run_by_default(tmp_path: Path) -> None:
    cohort = tmp_path / "cohort.json"
    run_dashboard(
        "init",
        "--course",
        "Demo",
        "--date",
        "2026-08-17",
        "--output",
        str(cohort),
    )
    proc = run_dashboard("create-issues", str(cohort))

    assert proc.returncode == 0, proc.stdout + proc.stderr
    commands = json.loads(proc.stdout)
    assert len(commands) == 3
    assert commands[0]["apply"] is False
    assert commands[0]["command"][:3] == ["gh", "issue", "create"]


def test_dashboard_has_report_drag_and_drop_controls() -> None:
    html = HTML.read_text(encoding="utf-8")

    assert "보고서 파일 드래그앤드롭" in html
    assert 'class="dropzone' in html
    assert 'event.dataTransfer.files[0]' in html
    assert "showToast(`${report.id} 보고서를 연결했습니다.`)" in html
