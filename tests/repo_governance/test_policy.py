from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "scripts" / "repo-governance" / "audit.py"
CREATE = ROOT / "scripts" / "repo-governance" / "create.py"
APPLY = ROOT / "scripts" / "repo-governance" / "apply.py"


def load_audit_module():
    spec = importlib.util.spec_from_file_location("repo_governance_audit", AUDIT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_cmd(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_policy_validates_offline() -> None:
    proc = run_cmd(str(AUDIT), "--offline", "--json")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)
    assert data["status"] == "pass"
    assert data["findings"] == []


def test_hypeprooflab_public_target_has_security_blocker() -> None:
    proc = run_cmd(str(AUDIT), "--offline", "--json")
    assert proc.returncode == 0, proc.stdout + proc.stderr

    import yaml

    policy = yaml.safe_load((ROOT / "policy" / "repos.yaml").read_text(encoding="utf-8"))
    lab = next(repo for repo in policy["repositories"] if repo["name"] == "hypeprooflab")
    assert lab["visibility"] == "private"
    assert lab["target_visibility"] == "public"
    blocker_issues = {item["issue"] for item in lab["public_readiness"]["blocked_by"]}
    assert "jayleekr/hypeprooflab#96" in blocker_issues
    assert any(exc["id"] == "temporary-private-until-oauth-purge" for exc in lab["exceptions"])


def test_hypeprooflab_hold_names_the_history_clearance_prerequisite() -> None:
    """The public flip is irreversible, so the prerequisite must be in policy.

    Nothing in this repo acts on `target_visibility` — apply.py never sends
    `visibility` to GitHub — so the hold is only as strong as what a human reads
    here. Pin the blocker and the exception so neither is dropped silently.
    """
    import yaml

    policy = yaml.safe_load((ROOT / "policy" / "repos.yaml").read_text(encoding="utf-8"))
    lab = next(repo for repo in policy["repositories"] if repo["name"] == "hypeprooflab")

    blockers = {item["issue"]: item["reason"] for item in lab["public_readiness"]["blocked_by"]}
    assert "jayleekr/hypeproof-harness#98" in blockers, "history-clearance blocker removed"
    reason = blockers["jayleekr/hypeproof-harness#98"]
    assert "history purge" in reason
    assert "TENANT-BOUNDARY-v0.1.md" in reason

    exceptions = {exc["id"]: exc for exc in lab["exceptions"]}
    assert "lab-public-readiness-tenant-history-clearance" in exceptions


def test_unresolved_public_readiness_blocker_forbids_public_visibility() -> None:
    """Flipping `visibility` to public used to satisfy every rule at once.

    The `target_visibility` block only runs while target != visibility, so the
    edit that violated the hold also switched the hold off. That is the one
    transition that cannot be undone, so it has to be a policy error.
    """
    module = load_audit_module()
    policy = module.load_policy()
    lab = next(
        repo for repo in policy["repos"]["repositories"] if repo["name"] == "hypeprooflab"
    )
    assert lab["public_readiness"]["blocked_by"], "fixture needs an unresolved blocker"

    assert module.validate_policy(policy) == [], "baseline policy must be valid"

    lab["visibility"] = "public"
    findings = module.validate_policy(policy)
    hold = [f for f in findings if f.field == "visibility"]
    assert len(hold) == 1, findings
    assert hold[0].severity == "critical"
    assert hold[0].apply_supported is False
    assert "unresolved blocker" in hold[0].message

    # Deleting the blockers is the sanctioned release path, not a bypass: it is a
    # visible diff that has to claim the work is done. Keep it working, so the
    # guard never becomes a reason to flip visibility instead.
    lab["public_readiness"]["blocked_by"] = []
    lab["target_visibility"] = "public"
    assert [f for f in module.validate_policy(policy) if f.field == "visibility"] == []


def test_create_plans_known_profile() -> None:
    proc = run_cmd(str(CREATE), "--repo", "jayleekr/example-product", "--profile", "public-product")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)
    assert data["status"] == "planned"
    assert "apply branch protection" in data["steps"]


def test_create_rejects_unknown_profile() -> None:
    proc = run_cmd(str(CREATE), "--repo", "jayleekr/example-product", "--profile", "missing")
    assert proc.returncode == 4


def test_apply_dry_run_plans_known_repo() -> None:
    proc = run_cmd(str(APPLY), "--repo", "hypeproof-harness", "--dry-run")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "DRY jayleekr/hypeproof-harness repo_settings" in proc.stdout
    assert "DRY jayleekr/hypeproof-harness labels UPSERT human-needed" in proc.stdout
    assert "DRY jayleekr/hypeproof-harness collaborators PUT repos/jayleekr/hypeproof-harness/collaborators/TJ-kr" in proc.stdout
    assert "branch_protection" in proc.stdout


def test_apply_dry_run_uses_repo_protected_branch_override() -> None:
    proc = run_cmd(str(APPLY), "--repo", "jayleekr.github.io", "--dry-run")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "repos/jayleekr/jayleekr.github.io/branches/master/protection" in proc.stdout


def test_apply_dry_run_can_limit_to_collaborators() -> None:
    proc = run_cmd(str(APPLY), "--repo", "sediment", "--module", "collaborators", "--dry-run")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "DRY jayleekr/sediment collaborators PUT repos/jayleekr/sediment/collaborators/TJ-kr" in proc.stdout
    assert "repo_settings" not in proc.stdout
    assert "branch_protection" not in proc.stdout


def test_live_governance_workflow_is_scheduled_and_manual() -> None:
    import yaml

    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "repo-governance-live.yml").read_text(encoding="utf-8"))
    triggers = workflow[True]
    assert "schedule" in triggers
    assert "workflow_dispatch" in triggers
    assert workflow["jobs"]["audit"]["env"]["GH_TOKEN"] == "${{ secrets.HYPEPROOF_GOVERNANCE_TOKEN || github.token }}"


def test_collaborator_audit_marks_pending_invitation() -> None:
    module = load_audit_module()
    policy = module.load_policy()
    repo = next(item for item in policy["repos"]["repositories"] if item["name"] == "sediment")
    profile = policy["profiles"][repo["profile"]]

    # 협업자 목록은 정본에서 만든다 — TJ-kr 한 명만 빼고 전원이 이미 붙어 있는 상태로.
    # 이름을 손으로 적어두면 멤버가 늘 때마다 findings 가 하나씩 늘어 이 테스트가
    # "초대 대기 한 건을 잡는다"가 아니라 "멤버 수가 그대로다"를 검사하게 된다.
    desired = module.desired_collaborators(policy["members"], profile, repo)
    already = [
        {"login": login,
         "permissions": {"admin": True} if perm == "admin" else {"push": True, "pull": True}}
        for login, perm in desired.items()
        if login != "TJ-kr"
    ]

    def fake_gh(path: str):
        if path.endswith("/collaborators"):
            return 0, already
        if path.endswith("/invitations"):
            return 0, [{"invitee": {"login": "TJ-kr"}, "permissions": "write"}]
        raise AssertionError(path)

    findings = module._audit_collaborators("jayleekr/sediment", repo, policy["members"], profile, fake_gh)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.field == "TJ-kr"
    assert finding.actual == "pending:write"
    assert finding.apply_supported is False
    assert "reviewer requests may fail" in finding.message


def test_collaborator_audit_marks_insufficient_pending_invitation() -> None:
    module = load_audit_module()
    policy = module.load_policy()
    repo = next(item for item in policy["repos"]["repositories"] if item["name"] == "jayleekr.github.io")
    profile = dict(policy["profiles"][repo["profile"]])
    profile["collaborators"] = dict(profile["collaborators"], admin_permission="admin")

    def fake_gh(path: str):
        if path.endswith("/collaborators"):
            return 0, [{"login": "jayleekr", "permissions": {"admin": True}}]
        if path.endswith("/invitations"):
            return 0, [{"invitee": {"login": "JeHyeong2"}, "permissions": "write"}]
        raise AssertionError(path)

    findings = module._audit_collaborators("jayleekr/jayleekr.github.io", repo, policy["members"], profile, fake_gh)
    by_login = {finding.field: finding for finding in findings}
    assert by_login["JeHyeong2"].expected == "admin"
    assert by_login["JeHyeong2"].actual == "pending:write"
    assert by_login["JeHyeong2"].apply_supported is True
    assert "lower permission" in by_login["JeHyeong2"].message


def test_release_artifact_collaborators_are_maintainer_only_for_personal_repos() -> None:
    module = load_audit_module()
    policy = module.load_policy()
    repo = next(item for item in policy["repos"]["repositories"] if item["name"] == "hypeproof-studio-releases")
    profile = policy["profiles"]["release-artifact"]
    desired = module.desired_collaborators(policy["members"], profile, repo)
    assert desired == {"jayleekr": "admin", "JeHyeong2": "write"}


def _retired_repos(policy) -> list:
    """Every repo declared under the retired-repository profile.

    Keyed on the PROFILE, not a repo name: a retirement ends with the repo
    actually being deleted and its entry removed (Claude-Code-Remote, #40), so
    hardcoding one would break the suite the moment a retirement completes.
    """
    return [
        item
        for item in policy["repos"]["repositories"]
        if item.get("profile") == "retired-repository"
    ]


def test_retired_repository_tracks_deletion_and_owner_only_access() -> None:
    module = load_audit_module()
    policy = module.load_policy()
    repos = _retired_repos(policy)
    if not repos:
        pytest.skip("no repo currently declared retired-repository (last retirement completed)")
    profile = policy["profiles"]["retired-repository"]

    for repo in repos:
        desired = module.desired_collaborators(policy["members"], profile, repo)
        assert repo["lifecycle"] == "retired"
        # A retirement must name the issue that authorises it and say why.
        assert repo["retirement"]["issue"].startswith("jayleekr/")
        assert repo["retirement"]["reason"]
        assert desired == {"jayleekr": "admin"}


def test_retired_repository_audit_checks_archive_and_disabled_features(monkeypatch) -> None:
    module = load_audit_module()
    policy = module.load_policy()
    repos = _retired_repos(policy)
    if not repos:
        pytest.skip("no repo currently declared retired-repository (last retirement completed)")
    repo = repos[0]
    profile = policy["profiles"]["retired-repository"]
    full_name = f"{repo['owner']}/{repo['name']}"

    def fake_gh(path: str):
        if path == f"repos/{full_name}":
            return 0, {
                "visibility": repo.get("visibility", "public"),
                "default_branch": repo.get("default_branch", "main"),
                "archived": False,
                "has_issues": True,
                "has_wiki": True,
                "has_projects": False,
            }
        if path.endswith("/collaborators") or path.endswith("/invitations"):
            return 0, []
        if path.endswith("/actions/permissions/workflow"):
            return 0, {}
        if path.endswith("/actions/permissions"):
            return 0, {"enabled": True}
        raise AssertionError(path)

    monkeypatch.setattr(module, "gh_json", fake_gh)
    findings = module.live_audit_repo(repo, profile, policy["members"])
    by_field = {finding.field: finding for finding in findings}

    assert by_field["archived"].expected is True
    assert by_field["archived"].actual is False
    assert by_field["has_issues"].expected is False
    assert by_field["has_wiki"].expected is False
    assert by_field["enabled"].module == "actions"
