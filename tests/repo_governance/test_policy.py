from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "scripts" / "repo-governance" / "audit.py"
CREATE = ROOT / "scripts" / "repo-governance" / "create.py"
APPLY = ROOT / "scripts" / "repo-governance" / "apply.py"
MEMBERS = ROOT / "policy" / "members.yaml"
HARNESS_CODEOWNERS = ROOT / ".github" / "CODEOWNERS"
TEMPLATE_CODEOWNERS = ROOT / "policy" / "templates" / "common" / "CODEOWNERS"


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


def test_codeowners_requests_every_member() -> None:
    import yaml

    members_doc = yaml.safe_load(MEMBERS.read_text())
    expected = {
        f"@{login}"
        for group in ("admins", "writers")
        for login in members_doc["members"][group]
    }

    for path in (HARNESS_CODEOWNERS, TEMPLATE_CODEOWNERS):
        owners = {
            token
            for line in path.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
            for token in line.split()[1:]
            if token.startswith("@")
        }
        assert expected <= owners, f"{path} missing {sorted(expected - owners)}"
