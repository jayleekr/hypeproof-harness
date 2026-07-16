from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "hype-review" / "review.py"
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
    assert "hype-review" in sync.split("SKILLS=(", 1)[1].split(")", 1)[0]
