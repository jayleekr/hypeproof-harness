from __future__ import annotations

import argparse
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


def _create_args(module, **overrides):
    defaults = dict(
        repo="hypeproof-studio",
        head="feat/example",
        base=module.DEFAULT_BASE,
        title="Example PR",
        body="Closes #1",
        body_file=None,
        author="TJ-kr",
        path=["docs/dev/usage-notes.md"],
        label=[],
        draft=False,
        auto_merge=True,
        apply=True,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class _FakeGh:
    """Records gh invocations and returns canned results by subcommand."""

    def __init__(self, module):
        self.module = module
        self.calls: list[list[str]] = []

    def __call__(self, cmd, *, input_text=None):
        self.calls.append(cmd)
        # `gh pr create` prints the created PR URL on the last line.
        if cmd[:3] == ["gh", "pr", "create"]:
            return self.module.CommandResult(0, "https://github.com/x/y/pull/99", "")
        return self.module.CommandResult(0, "ok", "")

    def merge_calls(self):
        return [c for c in self.calls if c[:3] == ["gh", "pr", "merge"]]


def test_create_apply_enables_auto_merge_when_eligible(monkeypatch) -> None:
    module = load_module()
    policy = module.load_policy()
    fake = _FakeGh(module)
    monkeypatch.setattr(module, "run", fake)

    rc = module.command_create(_create_args(module), policy)

    assert rc == 0
    # PR created, every non-author reviewer requested, and auto-merge enabled.
    assert any(c[:3] == ["gh", "pr", "create"] for c in fake.calls)
    assert any("--add-reviewer" in c for c in fake.calls)
    merge = fake.merge_calls()
    assert len(merge) == 1
    assert merge[0][:4] == ["gh", "pr", "merge", "https://github.com/x/y/pull/99"]
    assert "--auto" in merge[0]
    assert f"--{module.AUTO_MERGE_METHOD}" in merge[0]
    assert "--delete-branch" in merge[0]


def test_create_apply_does_not_merge_high_risk_pr(monkeypatch) -> None:
    module = load_module()
    policy = module.load_policy()
    fake = _FakeGh(module)
    monkeypatch.setattr(module, "run", fake)

    # A governance path must keep auto-merge ineligible even with --apply.
    args = _create_args(module, path=["policy/repos.yaml"])
    rc = module.command_create(args, policy)

    assert rc == 0
    assert any(c[:3] == ["gh", "pr", "create"] for c in fake.calls)
    assert fake.merge_calls() == []
