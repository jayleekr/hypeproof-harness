from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "scripts" / "repo-governance" / "audit.py"
CREATE = ROOT / "scripts" / "repo-governance" / "create.py"
APPLY = ROOT / "scripts" / "repo-governance" / "apply.py"


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
    assert "branch_protection" in proc.stdout


def test_apply_dry_run_uses_repo_protected_branch_override() -> None:
    proc = run_cmd(str(APPLY), "--repo", "jayleekr.github.io", "--dry-run")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "repos/jayleekr/jayleekr.github.io/branches/master/protection" in proc.stdout
