from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANNOUNCE = ROOT / "scripts" / "weekly-harness" / "announce.py"

CYCLE = "weekly-2026-07-27"
PREV = "weekly-2026-07-20"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ANNOUNCE), *args],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )


def issue(number, title, owner=None, state="OPEN", repo="jayleekr/sediment"):
    body = f"## Owner\n\n담당: @{owner}\n" if owner else ""
    return {
        "number": number, "title": title, "state": state, "body": body,
        "assignees": [], "url": f"https://github.com/{repo}/issues/{number}",
    }


def write(tmp_path, issues=None, milestones=None):
    ipath = tmp_path / "issues.json"
    ipath.write_text(json.dumps(issues or {}), encoding="utf-8")
    args = ["--cycle", CYCLE, "--prev-cycle", PREV, "--issues-json", str(ipath)]
    if milestones is not None:
        mpath = tmp_path / "ms.json"
        mpath.write_text(json.dumps(milestones), encoding="utf-8")
        args += ["--milestones-json", str(mpath)]
    else:
        args += ["--milestones-json", str(tmp_path / "empty.json")]
        (tmp_path / "empty.json").write_text("{}", encoding="utf-8")
    return args


def test_bad_cycle_label_is_rejected() -> None:
    proc = run("--cycle", "2026-07-27", "--issues-json", "/dev/null")
    assert proc.returncode == 2
    assert "bad cycle label" in proc.stderr


def test_groups_this_cycle_issues_by_owner(tmp_path) -> None:
    issues = {
        f"jayleekr/sediment::{CYCLE}": [
            issue(201, "wire deploy notify", owner="JeHyeong2"),
            issue(202, "PR discord channel", owner="JinyongShin"),
        ],
    }
    proc = run(*write(tmp_path, issues), "--repo", "jayleekr/sediment")
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "## 이번 주 배정 (담당자별)" in out
    assert "### @JeHyeong2 — 1건" in out
    assert "### @JinyongShin — 1건" in out
    assert "sediment#201" in out and "sediment#202" in out


def test_carry_over_lists_prev_cycle_open_issues(tmp_path) -> None:
    issues = {
        f"jayleekr/sediment::{PREV}": [
            issue(118, "verify L1/L2/L3", owner="jayleekr", state="OPEN"),
            issue(121, "ingest notes", owner="jayleekr", state="CLOSED"),
        ],
    }
    proc = run(*write(tmp_path, issues), "--repo", "jayleekr/sediment")
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert f"## 지난 사이클 이월 (`{PREV}` 미완)" in out
    assert "sediment#118" in out          # open -> carried
    assert "sediment#121" not in out      # closed -> not carried
    assert "미완 1건" in out


def test_prev_cycle_defaults_to_seven_days_before(tmp_path) -> None:
    # Omit --prev-cycle: it must derive weekly-2026-07-20 from the cycle.
    issues = {f"jayleekr/sediment::{PREV}": [issue(118, "verify", owner="jayleekr")]}
    ipath = tmp_path / "i.json"; ipath.write_text(json.dumps(issues), encoding="utf-8")
    epath = tmp_path / "e.json"; epath.write_text("{}", encoding="utf-8")
    proc = run("--cycle", CYCLE, "--issues-json", str(ipath),
               "--milestones-json", str(epath), "--repo", "jayleekr/sediment")
    assert proc.returncode == 0, proc.stderr
    assert PREV in proc.stdout and "sediment#118" in proc.stdout


def test_milestone_progress_rendered(tmp_path) -> None:
    ms = {"jayleekr/hypeproof-studio": [
        {"title": "8/29 강의", "state": "open", "due_on": "2026-08-29T00:00:00Z",
         "open_issues": 3, "closed_issues": 1},
    ]}
    proc = run(*write(tmp_path, {}, ms), "--repo", "jayleekr/hypeproof-studio",
               "--milestone-repo", "jayleekr/hypeproof-studio")
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "## 마일스톤 현황" in out
    assert "8/29 강의" in out
    assert "2026-08-29" in out
    assert "1/4 (25%)" in out


def test_empty_everything_is_still_valid_markdown(tmp_path) -> None:
    proc = run(*write(tmp_path, {}), "--repo", "jayleekr/sediment")
    assert proc.returncode == 0, proc.stderr
    assert "라벨이 붙은 이슈가 아직 없습니다" in proc.stdout
    assert "이월된 미완 항목이 없습니다" in proc.stdout
    assert "추적 중인 마일스톤이 없습니다" in proc.stdout
