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
        "--issue",
        "1",
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
        issue=1,
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
        if cmd[:4] == ["gh", "api", "--method", "GET"]:
            number = int(cmd[-1].rsplit("/", 1)[-1])
            issue = {"number": number, "state": "open", "title": "fix: scoped work", "labels": [],
                     "pull_request": None, "created_at": "2026-09-22T00:00:00Z",
                     "html_url": f"https://github.com/x/y/issues/{number}"}
            return self.module.CommandResult(0, json.dumps(issue), "")
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


def test_scoped_issue_rejects_wrong_closing_target() -> None:
    module = load_module()
    issue = {"number": 7, "state": "open", "title": "fix: scoped", "labels": [],
             "pull_request": None, "created_at": "2026-09-22T00:00:00Z"}
    import pytest
    with pytest.raises(ValueError, match="only scoped issue"):
        module.validate_scoped_issue(issue, "jayleekr/hypeproof-studio", 7, "Closes #7\nCloses: #8")


def test_scoped_issue_rejects_closed_pull_request_and_epic() -> None:
    module = load_module()
    base = {"number": 7, "state": "open", "title": "fix: scoped", "labels": [],
            "pull_request": None, "created_at": "2026-09-22T00:00:00Z"}
    import pytest
    for changed, message in [
        ({"state": "closed"}, "must be open"),
        ({"pull_request": {"url": "x"}}, "pull request"),
        ({"labels": [{"name": "Epic"}]}, "Epic"),
        ({"type": {"name": "Epic"}}, "Epic"),
        ({"title": "[arch] EPIC: broad work"}, "Epic"),
    ]:
        with pytest.raises(ValueError, match=message):
            module.validate_scoped_issue({**base, **changed}, "jayleekr/hypeproof-studio", 7, "Closes #7")


def test_scoped_issue_accepts_same_repo_open_issue() -> None:
    module = load_module()
    issue = {"number": 7, "state": "open", "title": "fix: scoped", "labels": [],
             "pull_request": None, "created_at": "2026-09-22T00:00:00Z", "html_url": "https://example/7"}
    result = module.validate_scoped_issue(issue, "jayleekr/hypeproof-studio", 7,
                                          "Fixes jayleekr/hypeproof-studio#7")
    assert result["number"] == 7


def test_closing_issue_targets_cover_github_keywords_and_urls() -> None:
    module = load_module()
    from issue_guard import closing_issue_targets
    body = "\n".join([
        "Close #7", "Closes #7", "Closed #7", "Fix #7", "Fixes #7", "Fixed #7",
        "Resolve #7", "Resolves #7", "Resolved #7", "Closes: #7",
        "Fixes https://github.com/jayleekr/hypeproof-studio/issues/7",
    ])
    assert closing_issue_targets(body, "jayleekr/hypeproof-studio") == [
        ("jayleekr/hypeproof-studio", 7)
    ] * 11


def test_scoped_issue_rejects_hidden_full_url_closing_target() -> None:
    module = load_module()
    issue = {"number": 7, "state": "open", "title": "fix: scoped", "labels": [],
             "pull_request": None, "created_at": "2026-09-22T00:00:00Z"}
    import pytest
    body = "Closes #7\nFixes https://github.com/jayleekr/hypeproof-studio/issues/751"
    with pytest.raises(ValueError, match="only scoped issue"):
        module.validate_scoped_issue(issue, "jayleekr/hypeproof-studio", 7, body)


def test_create_parser_rejects_non_positive_issue_number() -> None:
    module = load_module()
    import pytest
    with pytest.raises(SystemExit):
        module.build_parser().parse_args([
            "create", "--repo", "hypeproof-studio", "--head", "fix/x", "--title", "x",
            "--author", "TJ-kr", "--issue", "0",
        ])


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


def _canonical_pair(tmp_path):
    """Build an origin and a clone of it, both with one commit on main."""
    origin, clone = tmp_path / "origin", tmp_path / "clone"
    subprocess.run(["git", "init", "--quiet", "--initial-branch", "main", str(origin)], check=True)
    (origin / "seed.txt").write_text("1\n")
    for args in (["add", "seed.txt"], ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "--quiet", "-m", "seed"]):
        subprocess.run(["git", "-C", str(origin), *args], check=True)
    subprocess.run(["git", "clone", "--quiet", str(origin), str(clone)], check=True)
    return origin, clone


def _advance(origin, text):
    (origin / "seed.txt").write_text(text)
    for args in (["add", "seed.txt"], ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "--quiet", "-m", text]):
        subprocess.run(["git", "-C", str(origin), *args], check=True)


def _head(path):
    return subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], text=True, capture_output=True).stdout.strip()


def test_refresh_canonical_fast_forwards_a_behind_checkout(tmp_path):
    origin, clone = _canonical_pair(tmp_path)
    _advance(origin, "2\n")

    assert load_module().refresh_canonical(clone) is None
    assert _head(clone) == _head(origin)


def test_refresh_canonical_returns_to_main_from_a_feature_branch(tmp_path):
    origin, clone = _canonical_pair(tmp_path)
    subprocess.run(["git", "-C", str(clone), "checkout", "--quiet", "-b", "feat/left-here"], check=True)
    _advance(origin, "2\n")

    assert load_module().refresh_canonical(clone) is None
    assert _head(clone) == _head(origin)
    # The branch is repaired by moving the checkout, never by dropping its commits.
    assert subprocess.run(["git", "-C", str(clone), "rev-parse", "--verify", "feat/left-here"],
                          capture_output=True).returncode == 0


def test_refresh_canonical_refuses_to_overwrite_uncommitted_work(tmp_path):
    origin, clone = _canonical_pair(tmp_path)
    _advance(origin, "2\n")
    (clone / "seed.txt").write_text("mine\n")

    assert "uncommitted" in (load_module().refresh_canonical(clone) or "")
    assert (clone / "seed.txt").read_text() == "mine\n"


def test_refresh_canonical_refuses_when_local_commits_are_not_upstream(tmp_path):
    origin, clone = _canonical_pair(tmp_path)
    _advance(origin, "2\n")
    (clone / "local.txt").write_text("keep\n")
    for args in (["add", "local.txt"], ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "--quiet", "-m", "local only"]):
        subprocess.run(["git", "-C", str(clone), *args], check=True)
    unpushed = _head(clone)

    assert "not on origin/main" in (load_module().refresh_canonical(clone) or "")
    assert _head(clone) == unpushed


def test_refresh_canonical_is_skipped_when_pinned(tmp_path, monkeypatch):
    origin, clone = _canonical_pair(tmp_path)
    _advance(origin, "2\n")
    behind = _head(clone)
    monkeypatch.setenv("HYPEPROOF_HARNESS_PIN", "1")

    assert load_module().refresh_canonical(clone) is None
    assert _head(clone) == behind


def _stamp(consumer, sha):
    (consumer / "scripts/hype-pr").mkdir(parents=True, exist_ok=True)
    (consumer / "scripts/hype-pr/HARNESS_VERSION").write_text(sha + "\n")


def test_bundle_drift_is_silent_when_the_installed_revision_is_current(tmp_path):
    module = load_module()
    consumer = tmp_path / "consumer"
    _stamp(consumer, _head(ROOT))

    assert module.bundle_drift(ROOT, consumer) is None


def _commit(repo, path, text, message):
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(text)
    subprocess.run(["git", "-C", str(repo), "add", path], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "--quiet", "-m", message], check=True)
    return _head(repo)


def test_bundle_drift_ignores_harness_commits_that_miss_the_bundle(tmp_path):
    """A consumer that went red every time Harness moved would be muted in a week."""
    module = load_module()
    canonical, consumer = tmp_path / "canonical", tmp_path / "consumer"
    subprocess.run(["git", "init", "--quiet", "--initial-branch", "main", str(canonical)], check=True)
    installed = _commit(canonical, "scripts/hype-pr/pr.py", "bundle v1\n", "bundle")
    _commit(canonical, "policy/repos.yaml", "unrelated\n", "policy only")
    _stamp(consumer, installed)

    assert module.bundle_drift(canonical, consumer) is None

    _commit(canonical, "scripts/hype-pr/pr.py", "bundle v2\n", "bundle moves")
    assert "has changed since" in (module.bundle_drift(canonical, consumer) or "")


def test_bundle_drift_reports_a_revision_whose_bundle_differs(tmp_path):
    module = load_module()
    consumer = tmp_path / "consumer"
    changed = subprocess.run(["git", "-C", str(ROOT), "log", "-2", "--format=%H", "--",
                              "scripts/hype-pr/pr.py"], text=True, capture_output=True).stdout.split()
    if len(changed) < 2:
        import pytest
        pytest.skip("bundle has too little history to compare")
    _stamp(consumer, changed[1])

    assert "has changed since" in (module.bundle_drift(ROOT, consumer) or "")


def test_bundle_drift_names_an_unknown_revision_instead_of_passing(tmp_path):
    module = load_module()
    consumer = tmp_path / "consumer"
    _stamp(consumer, "0" * 40)

    assert "unknown to the canonical checkout" in (module.bundle_drift(ROOT, consumer) or "")


def test_bundle_drift_is_silent_without_a_stamp(tmp_path):
    # The Harness checkout itself carries no stamp and must not warn about itself.
    assert load_module().bundle_drift(ROOT, tmp_path / "consumer") is None
