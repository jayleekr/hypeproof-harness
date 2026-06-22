from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "hype-pr" / "pr.py"


def run_pr(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def load_module():
    spec = importlib.util.spec_from_file_location("hype_pr", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["hype_pr"] = module
    spec.loader.exec_module(module)
    return module


def test_plan_requests_every_active_member_except_author() -> None:
    proc = run_pr(
        "plan",
        "--repo",
        "hypeproof-studio",
        "--author",
        "JinyongShin",
        "--path",
        "docs/dev/cohort.md",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)

    assert data["repo"] == "jayleekr/hypeproof-studio"
    assert data["review_request"]["exclude_author"] is True
    assert data["review_request"]["active_members"] == [
        "jayleekr",
        "JeHyeong2",
        "ico1036",
        "xoqhdgh1002",
        "JinyongShin",
        "TJ-kr",
    ]
    assert data["reviewers"] == ["jayleekr", "JeHyeong2", "ico1036", "xoqhdgh1002", "TJ-kr"]


def test_auto_merge_is_blocked_when_profile_disallows_it() -> None:
    proc = run_pr(
        "plan",
        "--repo",
        "hypeprooflab",
        "--author",
        "ico1036",
        "--auto-merge",
        "--path",
        "docs/design/README.md",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)

    assert data["auto_merge"]["requested"] is True
    assert data["auto_merge"]["profile_allows"] is False
    assert data["auto_merge"]["eligible"] is False
    assert "profile_disallows_auto_merge" in data["auto_merge"]["blocked_by"]


def test_auto_merge_blocks_high_risk_paths_and_labels() -> None:
    proc = run_pr(
        "plan",
        "--repo",
        "sediment",
        "--author",
        "JeHyeong2",
        "--auto-merge",
        "--path",
        ".github/workflows/deploy.yml",
        "--path",
        "services/sediment/applications/auth/admin.py",
        "--path",
        "policy/repos.yaml",
        "--label",
        "human-needed",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)

    blocked = set(data["auto_merge"]["blocked_by"])
    assert "risk:deploy" in blocked
    assert "risk:security" in blocked
    assert "risk:governance" in blocked
    assert "label:human-needed" in blocked
    assert data["risk"]["auto_merge_blocking"] == ["deploy", "security", "governance"]


def test_auto_merge_can_be_eligible_when_profile_and_risk_allow_it() -> None:
    module = load_module()
    policy = module.load_policy()
    repo, profile = module.find_repo(policy, "hypeproof-studio")
    assert profile["repository"]["allow_auto_merge"] is True
    data = module.plan(
        policy=policy,
        repo_ref=module.repo_full_name(repo),
        author="TJ-kr",
        paths=["docs/dev/usage-notes.md"],
        labels=[],
        draft=False,
        auto_merge=True,
    )

    assert data["auto_merge"]["eligible"] is True
    assert data["auto_merge"]["blocked_by"] == []
    assert data["reviewers"] == ["jayleekr", "JeHyeong2", "ico1036", "xoqhdgh1002", "JinyongShin"]


def test_create_is_dry_run_by_default_and_includes_reviewers() -> None:
    proc = run_pr(
        "create",
        "--repo",
        "hypeproof-harness",
        "--head",
        "feat/example",
        "--title",
        "Example PR",
        "--body",
        "Closes #1",
        "--author",
        "jayleekr",
        "--path",
        "docs/HYPE-PR.ko.md",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)

    assert data["apply"] is False
    command = data["create_command"]
    assert command[:4] == ["gh", "pr", "create", "--repo"]
    assert "--reviewer" not in command

    reviewer_commands = data["reviewer_commands"]
    reviewer_args = [cmd[cmd.index("--add-reviewer") + 1] for cmd in reviewer_commands]
    assert "jayleekr" not in reviewer_args
    assert "JeHyeong2" in reviewer_args
    assert "TJ-kr" in reviewer_args
