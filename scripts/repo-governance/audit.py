#!/usr/bin/env python3
"""Audit HypeProof repository governance policy.

The script has two modes:

- offline validation: parse policy files and verify internal consistency
- live audit: compare the policy with GitHub repo settings through `gh api`

It intentionally does not mutate GitHub state. Apply/create tooling should call
the same policy loader but live behind manual approval.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - exercised in user env, not tests
    raise SystemExit("PyYAML is required: python3 -m pip install pyyaml") from exc


ROOT = Path(__file__).resolve().parents[2]
POLICY_DIR = ROOT / "policy"


@dataclass(frozen=True)
class Finding:
    repo: str
    module: str
    severity: str
    field: str
    expected: Any
    actual: Any
    apply_supported: bool = True
    message: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "module": self.module,
            "severity": self.severity,
            "field": self.field,
            "expected": self.expected,
            "actual": self.actual,
            "apply_supported": self.apply_supported,
            "message": self.message,
        }


def _load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"{path}: invalid YAML: {exc}") from exc


def load_policy(root: Path = ROOT) -> dict[str, Any]:
    policy_dir = root / "policy"
    repos = _load_yaml(policy_dir / "repos.yaml")
    members = _load_yaml(policy_dir / "members.yaml")
    profiles: dict[str, dict[str, Any]] = {}
    for path in sorted((policy_dir / "profiles").glob("*.yaml")):
        data = _load_yaml(path)
        name = data.get("profile")
        if not name:
            raise ValueError(f"{path}: missing profile")
        profiles[name] = data
    return {"repos": repos, "members": members, "profiles": profiles}


def validate_policy(policy: dict[str, Any], today: dt.date | None = None) -> list[Finding]:
    today = today or dt.date.today()
    findings: list[Finding] = []
    repos_doc = policy["repos"]
    members_doc = policy["members"]
    profiles = policy["profiles"]

    if repos_doc.get("version") != 1:
        findings.append(_policy_error("repos.yaml", "version", 1, repos_doc.get("version")))
    if members_doc.get("version") != 1:
        findings.append(_policy_error("members.yaml", "version", 1, members_doc.get("version")))

    seen: set[str] = set()
    for repo in repos_doc.get("repositories", []):
        full = repo_full_name(repo)
        if full in seen:
            findings.append(_policy_error(full, "duplicate_repo", "unique", full))
        seen.add(full)

        for key in ("owner", "name", "visibility", "profile", "default_branch", "lifecycle"):
            if not repo.get(key):
                findings.append(_policy_error(full, key, "present", repo.get(key)))

        profile_name = repo.get("profile")
        if profile_name not in profiles:
            findings.append(_policy_error(full, "profile", f"one of {sorted(profiles)}", profile_name))

        visibility = repo.get("visibility")
        valid_visibilities = ("public", "private", "internal")
        if visibility not in valid_visibilities:
            findings.append(_policy_error(full, "visibility", "public/private/internal", visibility))

        target_visibility = repo.get("target_visibility")
        if target_visibility is not None:
            if target_visibility not in valid_visibilities:
                findings.append(_policy_error(full, "target_visibility", "public/private/internal", target_visibility))
            if target_visibility != visibility:
                readiness = repo.get("public_readiness") or {}
                blockers = readiness.get("blocked_by") or []
                has_temporary_exception = any(
                    exc.get("id") == "temporary-private-until-oauth-purge"
                    for exc in repo.get("exceptions", []) or []
                )
                if not blockers:
                    findings.append(_policy_error(full, "public_readiness.blocked_by", "present when target_visibility differs", blockers))
                for index, blocker in enumerate(blockers):
                    missing = [key for key in ("issue", "reason") if not blocker.get(key)]
                    if missing:
                        findings.append(_policy_error(full, f"public_readiness.blocked_by[{index}]", "issue/reason", missing))
                if not has_temporary_exception:
                    findings.append(_policy_error(full, "exceptions", "temporary-private-until-oauth-purge", None))

        checks = repo.get("required_status_checks", [])
        if checks is not None and not isinstance(checks, list):
            findings.append(_policy_error(full, "required_status_checks", "list", type(checks).__name__))

        for exc in repo.get("exceptions", []) or []:
            missing = [k for k in ("id", "owner", "reason", "expires_at") if not exc.get(k)]
            if missing:
                findings.append(_policy_error(full, "exceptions", "id/owner/reason/expires_at", missing))
                continue
            try:
                expires = dt.date.fromisoformat(str(exc["expires_at"]))
            except ValueError:
                findings.append(_policy_error(full, f"exception:{exc.get('id')}:expires_at", "YYYY-MM-DD", exc.get("expires_at")))
                continue
            if expires < today:
                findings.append(Finding(
                    repo=full,
                    module="policy",
                    severity="high",
                    field=f"exception:{exc['id']}",
                    expected=f"expires_at >= {today.isoformat()}",
                    actual=expires.isoformat(),
                    apply_supported=False,
                    message="Expired policy exception",
                ))

    for profile_name, profile in profiles.items():
        if profile.get("version") != 1:
            findings.append(_policy_error(profile_name, "profile.version", 1, profile.get("version")))
        if profile.get("profile") != profile_name:
            findings.append(_policy_error(profile_name, "profile.name", profile_name, profile.get("profile")))
        for section in ("repository", "actions"):
            if section not in profile:
                findings.append(_policy_error(profile_name, section, "present", None))
        collaborator_scope = profile.get("collaborators", {}).get("manage")
        if collaborator_scope not in ("members", "admins"):
            findings.append(_policy_error(profile_name, "collaborators.manage", "members/admins", collaborator_scope))

    return findings


def _policy_error(repo: str, field: str, expected: Any, actual: Any) -> Finding:
    return Finding(
        repo=repo,
        module="policy",
        severity="critical",
        field=field,
        expected=expected,
        actual=actual,
        apply_supported=False,
    )


def repo_full_name(repo: dict[str, Any]) -> str:
    return f"{repo.get('owner')}/{repo.get('name')}"


def gh_json(path: str) -> tuple[int, Any]:
    proc = subprocess.run(
        ["gh", "api", path],
        text=True,
        capture_output=True,
        check=False,
    )
    body = proc.stdout.strip() or proc.stderr.strip()
    try:
        data = json.loads(body) if body else None
    except json.JSONDecodeError:
        data = body
    return proc.returncode, data


def live_audit_repo(repo: dict[str, Any], profile: dict[str, Any], members: dict[str, Any]) -> list[Finding]:
    full = repo_full_name(repo)
    findings: list[Finding] = []

    code, meta = gh_json(f"repos/{full}")
    if code != 0:
        return [Finding(full, "github", "critical", "repo", "reachable", meta, False)]

    compare_map = {
        "visibility": repo.get("visibility"),
        "default_branch": repo.get("default_branch"),
        "allow_forking": profile.get("repository", {}).get("allow_forking"),
        "allow_auto_merge": profile.get("repository", {}).get("allow_auto_merge"),
        "delete_branch_on_merge": profile.get("repository", {}).get("delete_branch_on_merge"),
    }
    merge_methods = profile.get("repository", {}).get("merge_methods", {})
    compare_map["allow_squash_merge"] = merge_methods.get("squash")
    compare_map["allow_merge_commit"] = merge_methods.get("merge_commit")
    compare_map["allow_rebase_merge"] = merge_methods.get("rebase")
    for field, expected in compare_map.items():
        if expected is not None and meta.get(field) != expected:
            findings.append(Finding(
                full,
                "repo_settings",
                "medium",
                field,
                expected,
                meta.get(field),
                apply_supported=(field != "allow_forking"),
                message="GitHub only exposes allow_forking mutations for org-owned private repositories" if field == "allow_forking" else "",
            ))

    findings.extend(_audit_security(full, meta, profile))
    findings.extend(_audit_collaborators(full, repo, members, profile))
    findings.extend(_audit_actions(full, repo, profile))
    findings.extend(_audit_branch(full, repo, profile))
    return findings


PERMISSION_RANK = {
    "none": 0,
    "read": 1,
    "triage": 2,
    "write": 3,
    "push": 3,
    "maintain": 4,
    "admin": 5,
}


def desired_collaborators(members: dict[str, Any], profile: dict[str, Any]) -> dict[str, str]:
    scope = profile.get("collaborators", {}).get("manage", "members")
    admins = set(members.get("members", {}).get("admins", []) or [])
    writers = set(members.get("members", {}).get("writers", []) or []) if scope == "members" else set()
    desired = {login: "admin" for login in admins}
    for login in writers - admins:
        desired[login] = "write"
    return desired


def _permission_from_collaborator(item: dict[str, Any]) -> str:
    perms = item.get("permissions") or {}
    if perms.get("admin"):
        return "admin"
    if perms.get("maintain"):
        return "maintain"
    if perms.get("push"):
        return "write"
    if perms.get("triage"):
        return "triage"
    if perms.get("pull"):
        return "read"
    return "none"


def _permission_satisfies(actual: str | None, expected: str) -> bool:
    return PERMISSION_RANK.get(actual or "none", 0) >= PERMISSION_RANK[expected]


def _audit_collaborators(
    full: str,
    repo: dict[str, Any],
    members: dict[str, Any],
    profile: dict[str, Any],
    gh=gh_json,
) -> list[Finding]:
    findings: list[Finding] = []
    desired = desired_collaborators(members, profile)
    owner = repo.get("owner")

    code, collaborators = gh(f"repos/{full}/collaborators")
    if code != 0:
        return [Finding(full, "collaborators", "high", "collaborators", "readable", collaborators, False)]

    actual = {owner: "admin"} if owner else {}
    for item in collaborators or []:
        login = (item.get("login") or "").strip()
        if login:
            actual[login] = _permission_from_collaborator(item)

    code, invitations = gh(f"repos/{full}/invitations")
    pending: dict[str, str] = {}
    if code == 0:
        for item in invitations or []:
            invitee = item.get("invitee") or {}
            login = (invitee.get("login") or "").strip()
            permission = item.get("permissions") or item.get("permission") or "write"
            if login:
                pending[login] = permission

    for login, expected in sorted(desired.items()):
        current = actual.get(login)
        if _permission_satisfies(current, expected):
            continue
        invited = pending.get(login)
        if invited and _permission_satisfies(invited, expected):
            findings.append(Finding(
                full,
                "collaborators",
                "high",
                login,
                expected,
                f"pending:{invited}",
                apply_supported=False,
                message="Invitation is pending; official reviewer requests may fail until the member accepts it",
            ))
            continue
        if invited:
            findings.append(Finding(
                full,
                "collaborators",
                "high",
                login,
                expected,
                f"pending:{invited}",
                apply_supported=True,
                message="Pending invitation has lower permission than policy requires",
            ))
            continue
        findings.append(Finding(
            full,
            "collaborators",
            "high",
            login,
            expected,
            current or "missing",
            apply_supported=True,
        ))
    return findings


def _audit_security(full: str, meta: dict[str, Any], profile: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    desired = profile.get("security", {})
    actual = meta.get("security_and_analysis")
    if desired and actual is None:
        return [Finding(full, "security", "medium", "security_and_analysis", desired, None, False, "GitHub plan or visibility may not expose this API")]
    for field, expected in desired.items():
        actual_status = (actual or {}).get(field, {}).get("status")
        if expected is not None and actual_status != expected:
            findings.append(Finding(full, "security", "medium", field, expected, actual_status))
    return findings


def _audit_actions(full: str, repo: dict[str, Any], profile: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    desired = profile.get("actions", {})
    if not desired:
        return findings

    code, perms = gh_json(f"repos/{full}/actions/permissions/workflow")
    if code == 0:
        for field in ("default_workflow_permissions", "can_approve_pull_request_reviews"):
            expected = desired.get(field)
            if expected is not None and perms.get(field) != expected:
                findings.append(Finding(full, "actions", "medium", field, expected, perms.get(field)))
    else:
        findings.append(Finding(full, "actions", "medium", "workflow_permissions", "readable", perms, False))

    code, general = gh_json(f"repos/{full}/actions/permissions")
    if code == 0:
        expected_enabled = desired.get("enabled")
        if expected_enabled is not None and general.get("enabled") != expected_enabled:
            findings.append(Finding(full, "actions", "medium", "enabled", expected_enabled, general.get("enabled")))
        expected_allowed = desired.get("allowed_actions")
        if expected_allowed is not None and general.get("allowed_actions") != expected_allowed:
            findings.append(Finding(full, "actions", "low", "allowed_actions", expected_allowed, general.get("allowed_actions")))

    if repo.get("visibility") == "public" and desired.get("fork_pr_approval"):
        code, approval = gh_json(f"repos/{full}/actions/permissions/fork-pr-contributor-approval")
        if code == 0 and approval.get("approval_policy") != desired["fork_pr_approval"]:
            findings.append(Finding(full, "actions", "medium", "fork_pr_approval", desired["fork_pr_approval"], approval.get("approval_policy")))
    return findings


def _audit_branch(full: str, repo: dict[str, Any], profile: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    desired = profile.get("branch_protection", {})
    if not desired:
        return findings

    branch = repo.get("protected_branch") or desired.get("branch") or repo.get("default_branch", "main")
    code, branch_meta = gh_json(f"repos/{full}/branches/{branch}")
    if code != 0:
        return [Finding(full, "branch_protection", "high", branch, "reachable", branch_meta, False)]
    if not branch_meta.get("protected"):
        private_plan_limited = repo.get("visibility") == "private"
        findings.append(Finding(
            full,
            "branch_protection",
            "high",
            "protected",
            True,
            False,
            apply_supported=not private_plan_limited,
            message="Private repo branch protection requires GitHub Pro/Team or an org plan" if private_plan_limited else "",
        ))
        return findings

    code, protection = gh_json(f"repos/{full}/branches/{branch}/protection")
    if code != 0:
        return [Finding(full, "branch_protection", "high", "protection", "readable", protection, False)]

    bool_fields = {
        "enforce_admins": ("enforce_admins", "enabled"),
        "allow_force_pushes": ("allow_force_pushes", "enabled"),
        "allow_deletions": ("allow_deletions", "enabled"),
        "required_linear_history": ("required_linear_history", "enabled"),
    }
    for desired_field, path in bool_fields.items():
        expected = desired.get(desired_field)
        if expected is None:
            continue
        node = protection.get(path[0]) or {}
        actual = node.get(path[1])
        if actual != expected:
            findings.append(Finding(full, "branch_protection", "high", desired_field, expected, actual))

    desired_review = desired.get("required_pull_request_reviews", {})
    actual_review = protection.get("required_pull_request_reviews") or {}
    for field, expected in desired_review.items():
        actual = actual_review.get(field)
        if actual != expected:
            findings.append(Finding(full, "branch_protection", "high", f"reviews.{field}", expected, actual))

    desired_checks = repo.get("required_status_checks", [])
    if desired_checks:
        actual_checks = protection.get("required_status_checks") or {}
        contexts = set(actual_checks.get("contexts") or [])
        missing = [check for check in desired_checks if check not in contexts]
        if missing:
            findings.append(Finding(full, "branch_protection", "high", "required_status_checks", desired_checks, sorted(contexts)))
    return findings


def render_text(findings: list[Finding]) -> str:
    if not findings:
        return "PASS: no policy drift found"
    rows = ["repo\tseverity\tmodule\tfield\texpected\tactual"]
    for f in findings:
        rows.append(
            "\t".join([
                f.repo,
                f.severity,
                f.module,
                f.field,
                json.dumps(f.expected, ensure_ascii=False),
                json.dumps(f.actual, ensure_ascii=False),
            ])
        )
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", help="owner/name or repo name from policy")
    parser.add_argument("--all", action="store_true", help="audit every repo")
    parser.add_argument("--offline", action="store_true", help="validate policy only; do not call GitHub")
    parser.add_argument("--json", action="store_true", help="print JSON")
    args = parser.parse_args(argv)

    try:
        policy = load_policy()
        findings = validate_policy(policy)
    except Exception as exc:
        findings = [Finding("policy", "policy", "critical", "load", "valid policy", str(exc), False)]
        if args.json:
            print(json.dumps({"status": "error", "findings": [f.as_dict() for f in findings]}, ensure_ascii=False, indent=2))
        else:
            print(render_text(findings))
        return 4

    if not args.offline:
        repos = policy["repos"].get("repositories", [])
        selected = []
        for repo in repos:
            full = repo_full_name(repo)
            if args.all or not args.repo or args.repo in (full, repo.get("name")):
                selected.append(repo)
        for repo in selected:
            profile = policy["profiles"][repo["profile"]]
            findings.extend(live_audit_repo(repo, profile, policy["members"]))

    status = "pass" if not findings else "drift"
    if args.json:
        print(json.dumps({"status": status, "findings": [f.as_dict() for f in findings]}, ensure_ascii=False, indent=2))
    else:
        print(render_text(findings))

    if any(f.module == "policy" and f.severity == "critical" for f in findings):
        return 4
    if any(not f.apply_supported for f in findings):
        return 3
    if findings:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
