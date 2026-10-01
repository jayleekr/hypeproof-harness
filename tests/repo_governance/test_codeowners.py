"""CODEOWNERS all-member rows must track policy/members.yaml (issue #249).

The template was hardcoded with six members while members.yaml grew to eight,
so two members never received automatic review requests in any repo. These
tests pin the drift check that now catches that, offline and live.
"""
from __future__ import annotations

import base64
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "scripts" / "repo-governance" / "audit.py"

MEMBERS = {
    "members": {
        "admins": ["alice", "Bob"],
        "writers": ["carol", "dave"],
    }
}
ALL = "@alice @Bob @carol @dave"


def load():
    spec = importlib.util.spec_from_file_location("repo_governance_audit", AUDIT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_active_members_keeps_policy_order() -> None:
    audit = load()
    assert audit.active_members(MEMBERS) == ["alice", "Bob", "carol", "dave"]


def test_complete_file_has_no_drift() -> None:
    audit = load()
    text = f"# comment\n* {ALL}\n/policy/ @alice @Bob\n/scripts/ {ALL}  # inline\n"
    assert audit.codeowners_drift(text, MEMBERS) == {}


def test_missing_member_on_catch_all_and_member_rows_is_reported() -> None:
    audit = load()
    text = "* @alice @Bob @carol\n/policy/ @alice @Bob\n/worker/ @alice @bob @CAROL\n"
    drift = audit.codeowners_drift(text, MEMBERS)
    # Maintainer-only /policy/ row is deliberate and left alone; logins compare
    # case-insensitively like GitHub does.
    assert drift == {
        "1 *": {"missing": ["dave"], "unknown": []},
        "3 /worker/": {"missing": ["dave"], "unknown": []},
    }


def test_former_member_is_reported_and_teams_are_ignored() -> None:
    audit = load()
    text = f"* {ALL} @mallory @org/team\n"
    assert audit.codeowners_drift(text, MEMBERS) == {"1 *": {"missing": [], "unknown": ["mallory"]}}


def test_catch_all_with_only_admins_is_drift() -> None:
    audit = load()
    assert audit.codeowners_drift("* @alice @Bob\n", MEMBERS) == {
        "1 *": {"missing": ["carol", "dave"], "unknown": []},
    }


def _gh(files: dict[str, str]):
    calls: list[str] = []

    def gh(path: str):
        calls.append(path)
        for rel, text in files.items():
            if path.startswith(f"repos/o/r/contents/{rel}?"):
                return 0, {"content": base64.b64encode(text.encode()).decode()}
        return 1, {"message": "Not Found", "status": "404"}

    return gh, calls


def test_live_audit_reports_drift_as_one_waivable_finding() -> None:
    audit = load()
    gh, calls = _gh({".github/CODEOWNERS": "* @alice @Bob @carol\n"})
    repo = {"owner": "o", "name": "r", "default_branch": "main"}
    findings = audit._audit_codeowners("o/r", repo, MEMBERS, {"collaborators": {"manage": "members"}}, gh)
    assert len(findings) == 1
    finding = findings[0]
    assert (finding.module, finding.field, finding.severity) == ("codeowners", "all_member_rows", "high")
    assert finding.actual == {"1 *": {"missing": ["dave"], "unknown": []}}
    assert "@alice @Bob @carol @dave" in finding.message
    assert calls == ["repos/o/r/contents/.github/CODEOWNERS?ref=main"]


def test_live_audit_falls_back_to_root_file_and_passes_when_complete() -> None:
    audit = load()
    gh, calls = _gh({"CODEOWNERS": f"* {ALL}\n"})
    repo = {"owner": "o", "name": "r", "default_branch": "master"}
    assert audit._audit_codeowners("o/r", repo, MEMBERS, {"collaborators": {"manage": "members"}}, gh) == []
    assert calls[-1] == "repos/o/r/contents/CODEOWNERS?ref=master"


def test_live_audit_skips_repos_without_file_or_member_scope() -> None:
    audit = load()
    gh, _ = _gh({})
    repo = {"owner": "o", "name": "r"}
    assert audit._audit_codeowners("o/r", repo, MEMBERS, {"collaborators": {"manage": "members"}}, gh) == []
    gh, calls = _gh({".github/CODEOWNERS": "* @alice @Bob\n"})
    assert audit._audit_codeowners("o/r", repo, MEMBERS, {"collaborators": {"manage": "admins"}}, gh) == []
    assert calls == []


def test_live_audit_reports_unreadable_file() -> None:
    audit = load()

    def gh(path: str):
        return 1, {"message": "Resource not accessible by integration", "status": "403"}

    findings = audit._audit_codeowners("o/r", {"owner": "o", "name": "r"}, MEMBERS, {}, gh)
    assert [(f.field, f.expected) for f in findings] == [("all_member_rows", "readable")]


def test_harness_codeowners_files_track_members_yaml() -> None:
    audit = load()
    policy = audit.load_policy()
    assert audit.audit_local_codeowners(policy["members"]) == []


def test_local_check_flags_stale_template(tmp_path: Path) -> None:
    audit = load()
    for rel in audit.LOCAL_CODEOWNERS_FILES:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(f"* {ALL}\n", encoding="utf-8")
    (tmp_path / "policy/templates/common/CODEOWNERS").write_text("* @alice @Bob @carol\n", encoding="utf-8")
    findings = audit.audit_local_codeowners(MEMBERS, tmp_path)
    assert [f.repo for f in findings] == ["local:policy/templates/common/CODEOWNERS"]
