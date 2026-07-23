"""Tests for the AI reviewer's pure logic — risk detection, verdict parsing,
and the fail-safe guard. The model call and gh submission are not exercised
here (no network); the safety contract that matters is that a blocker can never
become an approval and malformed model output never yields a silent pass."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import review_pr as rp  # noqa: E402


def test_detect_risks_flags_security_and_deploy():
    files = ["services/app/auth/login.py", ".github/workflows/ci.yml", "README.md"]
    risks = rp.detect_risks(files)
    assert "security" in risks
    assert "deploy" in risks
    assert "docs" in risks


def test_detect_risks_governance_and_data():
    assert "governance" in rp.detect_risks(["policy/repos.yaml"])
    assert "data" in rp.detect_risks(["services/db/migrations/001.sql"])


def test_detect_risks_empty_for_plain_change():
    assert rp.detect_risks(["src/util/format.ts".replace("ts", "txt")]) == []


def test_lens_questions_include_base_and_risk():
    qs = rp.lens_questions(["security"])
    assert any("테스트" in q for q in qs)          # a base question
    assert len(qs) == len(set(qs))                 # de-duplicated


def test_parse_verdict_plain_json():
    v = rp.parse_verdict('{"decision":"approve","summary":"ok","blockers":[],"questions":[]}')
    assert v["decision"] == "approve"


def test_parse_verdict_strips_fence_and_prose():
    text = 'Here is my review:\n```json\n{"decision":"comment","summary":"q"}\n```\n'
    v = rp.parse_verdict(text)
    assert v["decision"] == "comment"
    assert v["blockers"] == [] and v["questions"] == []  # defaults filled


def test_parse_verdict_rejects_bad_decision():
    with pytest.raises(ValueError):
        rp.parse_verdict('{"decision":"lgtm","summary":"x"}')


def test_parse_verdict_rejects_non_json():
    with pytest.raises(ValueError):
        rp.parse_verdict("the PR looks fine to me")


def test_enforce_safety_downgrades_approve_with_blockers():
    v = rp.enforce_safety({
        "decision": "approve",
        "summary": "s",
        "blockers": [{"file": "auth.py", "line": 3, "issue": "leaks token"}],
        "questions": [],
    })
    assert v["decision"] == "request_changes"
    assert v["_downgraded"] is True


def test_enforce_safety_leaves_clean_approve():
    v = rp.enforce_safety({"decision": "approve", "summary": "s", "blockers": [], "questions": []})
    assert v["decision"] == "approve"
    assert "_downgraded" not in v


def test_event_map_covers_all_decisions():
    assert set(rp.GH_EVENT) == {"approve", "comment", "request_changes"}


def test_render_body_marks_downgrade_and_blockers():
    v = {"decision": "request_changes", "summary": "s", "_downgraded": True,
         "blockers": [{"file": "a.py", "line": 1, "issue": "boom"}], "questions": ["q?"]}
    body = rp.render_body(v, ["security"])
    assert "Blocker" in body and "a.py:1" in body and "강등" in body
