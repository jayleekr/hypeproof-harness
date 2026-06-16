from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
from pathlib import Path


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


def test_collaborator_audit_marks_pending_invitation() -> None:
    module = load_audit_module()
    policy = module.load_policy()
    repo = next(item for item in policy["repos"]["repositories"] if item["name"] == "sediment")
    profile = policy["profiles"][repo["profile"]]

    def fake_gh(path: str):
        if path.endswith("/collaborators"):
            return 0, [
                {"login": "jayleekr", "permissions": {"admin": True}},
                {"login": "JeHyeong2", "permissions": {"admin": True}},
                {"login": "ico1036", "permissions": {"push": True, "pull": True}},
                {"login": "xoqhdgh1002", "permissions": {"push": True, "pull": True}},
                {"login": "JinyongShin", "permissions": {"push": True, "pull": True}},
            ]
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
    profile = policy["profiles"][repo["profile"]]

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


def test_release_artifact_collaborators_are_admin_only() -> None:
    module = load_audit_module()
    policy = module.load_policy()
    profile = policy["profiles"]["release-artifact"]
    desired = module.desired_collaborators(policy["members"], profile)
    assert desired == {"jayleekr": "admin", "JeHyeong2": "admin"}
