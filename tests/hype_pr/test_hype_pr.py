from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import yaml


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


def active_members_from_policy() -> list[str]:
    """정본(policy/members.yaml)의 활성 멤버를 admins → writers 순으로 준다.

    테스트가 이름 목록을 직접 들고 있으면 멤버가 한 명 늘 때마다 빨개진다. 그건 회귀가
    아니라 소음이고, 소음이 반복되면 사람이 빨간 걸 무시하게 된다. 여기서 확인할 것은
    "정본과 같은가" 이지 "그 이름이 무엇인가" 가 아니다.
    """
    doc = yaml.safe_load((ROOT / "policy" / "members.yaml").read_text(encoding="utf-8"))
    members = doc.get("members", {}) or {}
    return list(members.get("admins") or []) + list(members.get("writers") or [])


def load_module():
    spec = importlib.util.spec_from_file_location("hype_pr", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["hype_pr"] = module
    spec.loader.exec_module(module)
    return module


def test_plan_defaults_to_no_review_requests() -> None:
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
    assert data["review_request"]["enabled"] is False
    assert data["review_request"]["active_members"] == active_members_from_policy()
    assert data["reviewers"] == []
    assert data["review_request"]["requested_reviewers"] == []


def test_plan_requests_every_active_member_except_author_when_opted_in() -> None:
    proc = run_pr(
        "plan",
        "--repo",
        "hypeproof-studio",
        "--author",
        "JinyongShin",
        "--path",
        "docs/dev/cohort.md",
        "--request-reviewers",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)

    expected = [m for m in active_members_from_policy() if m != "JinyongShin"]
    assert data["review_request"]["enabled"] is True
    assert data["review_request"]["eligible_reviewers"] == expected
    assert data["reviewers"] == expected


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
    assert data["reviewers"] == []


def test_create_is_dry_run_by_default_without_reviewers() -> None:
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

    assert data["plan"]["review_request"]["enabled"] is False
    assert data["reviewer_commands"] == []
    cleanup_args = [cmd[cmd.index("--remove-reviewer") + 1] for cmd in data["reviewer_cleanup_commands"]]
    assert "jayleekr" not in cleanup_args
    assert "JeHyeong2" in cleanup_args


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
        request_reviewers=False,
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
    monkeypatch.setattr(module, "prepared_report", lambda args, policy: {"paths": args.path, "head": "a" * 40, "base_tip": "b" * 40, "tasks": [], "existing_debt": []})

    rc = module.command_create(_create_args(module), policy)

    assert rc == 0
    # PR created without adding reviewers; CODEOWNERS requests are cleared.
    assert any(c[:3] == ["gh", "pr", "create"] for c in fake.calls)
    assert not any("--add-reviewer" in c for c in fake.calls)
    assert any("--remove-reviewer" in c for c in fake.calls)
    merge = fake.merge_calls()
    assert len(merge) == 1
    assert merge[0][:4] == ["gh", "pr", "merge", "https://github.com/x/y/pull/99"]
    assert "--auto" in merge[0]
    assert f"--{module.AUTO_MERGE_METHOD}" in merge[0]
    assert "--delete-branch" in merge[0]


def test_create_apply_requests_reviewers_only_when_opted_in(monkeypatch) -> None:
    module = load_module()
    policy = module.load_policy()
    fake = _FakeGh(module)
    monkeypatch.setattr(module, "run", fake)
    monkeypatch.setattr(module, "prepared_report", lambda args, policy: {"paths": args.path, "head": "a" * 40, "base_tip": "b" * 40, "tasks": [], "existing_debt": []})

    rc = module.command_create(_create_args(module, request_reviewers=True), policy)

    assert rc == 0
    reviewer_calls = [c for c in fake.calls if "--add-reviewer" in c]
    assert reviewer_calls
    assert all("TJ-kr" not in c for c in reviewer_calls)
    assert not any("--remove-reviewer" in c for c in fake.calls)


def test_create_apply_does_not_merge_high_risk_pr(monkeypatch) -> None:
    module = load_module()
    policy = module.load_policy()
    fake = _FakeGh(module)
    monkeypatch.setattr(module, "run", fake)
    monkeypatch.setattr(module, "prepared_report", lambda args, policy: {"paths": args.path, "head": "a" * 40, "base_tip": "b" * 40, "tasks": [], "existing_debt": []})

    # A governance path must keep auto-merge ineligible even with --apply.
    args = _create_args(module, path=["policy/repos.yaml"])
    rc = module.command_create(args, policy)

    assert rc == 0
    assert any(c[:3] == ["gh", "pr", "create"] for c in fake.calls)
    assert fake.merge_calls() == []


def test_create_missing_receipt_never_calls_github(monkeypatch):
    module = load_module()
    monkeypatch.setattr(module, "run", lambda *_: (_ for _ in ()).throw(AssertionError("GitHub mutation before preparation")))
    import pytest
    with pytest.raises(ValueError, match="required"):
        module.command_create(_create_args(module), module.load_policy())


def test_actual_prepared_diff_overrides_claimed_low_risk_paths(monkeypatch):
    module = load_module(); fake = _FakeGh(module)
    monkeypatch.setattr(module, "run", fake)
    monkeypatch.setattr(module, "prepared_report", lambda *_: {"paths": ["policy/repos.yaml"], "head": "a" * 40, "base_tip": "b" * 40, "tasks": [], "existing_debt": []})
    assert module.command_create(_create_args(module, path=["docs/harmless.md"]), module.load_policy()) == 0
    assert not fake.merge_calls()
