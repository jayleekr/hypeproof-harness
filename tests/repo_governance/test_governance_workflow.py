"""The live-audit workflow's own control logic, tested against the committed text.

`repo-governance-live.yml` decides two things no human sees until it is too
late: whether a red run means "provision a credential", "investigate a lost
permission", or "remediate drift" — and whether a run that saw nothing counts
as a pass. Both have already gone wrong here:

  - The job shipped with `set +e … exit 0`, reporting success while its own
    artifact said `status: drift`, 64 findings, exit 3.
  - The first fix replaced that fail-open with a fail-silent: a preflight that
    aborted the whole audit as soon as ONE repo was readable-but-admin-hidden.
    A repo transferred away — real governance drift — would have been
    reclassified as a credential problem, silencing the other eight repos with
    it. A control must not reclassify an incident as a normal condition.

The step scripts are read out of the workflow YAML rather than copied, so these
tests exercise the text that actually runs. A regression in the workflow fails
here instead of going unnoticed until the next incident.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "repo-governance-live.yml"

HARNESS = "jayleekr/hypeproof-harness"
# Readable without admin: `gh api repos/cli/cli` succeeds but omits
# allow_auto_merge, which is exactly what losing admin on our own repo looks
# like. Used as the stand-in for "transferred away / access revoked".
NO_ADMIN = "cli/cli"


def workflow_steps(job: str) -> dict[str, str]:
    spec = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"][job]
    steps = {s["name"]: s["run"] for s in spec["steps"] if "run" in s and "name" in s}
    # CI runners expose `python`; developer machines may only have `python3`.
    return {k: re.sub(r"(?m)^(\s*)python(\s|$)", r"\1python3\2", v) for k, v in steps.items()}


AUDIT_STEPS = workflow_steps("audit")
GATE_STEPS = workflow_steps("weekly-loop-gate")


def run_step(script: str, cwd: Path, env: dict[str, str] | None = None):
    return subprocess.run(
        ["bash", "-e", "-c", script], cwd=cwd, capture_output=True, text=True,
        env={**os.environ, **(env or {})},
    )


@pytest.fixture()
def workdir():
    path = Path(tempfile.mkdtemp(prefix="gov-wf-"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def seed(workdir: Path, classification: str, findings: list[dict]) -> None:
    (workdir / "preflight-classification.txt").write_text(classification, encoding="utf-8")
    (workdir / "repo-governance-audit.json").write_text(
        json.dumps({"status": "drift" if findings else "pass", "findings": findings}),
        encoding="utf-8",
    )


def enforce(workdir: Path, status: str = "3"):
    return run_step(AUDIT_STEPS["Enforce"], workdir, {"STATUS": status})


# ------------------------------------------------------------ the incident ----


def test_losing_admin_on_one_repo_is_reported_as_drift_not_a_credential_excuse(workdir):
    """The failure mode that motivated this file.

    A repo we owned is transferred away, or our access to it is revoked. That is
    governance drift. It must not be renamed "credential problem", and above all
    it must not mute the findings from every other repo.
    """
    seed(
        workdir,
        f"ok {HARNESS}\nshallow {NO_ADMIN}\n",
        [
            {"repo": HARNESS, "severity": "high", "module": "branch_protection",
             "field": "reviews.required_approving_review_count"},
            {"repo": NO_ADMIN, "severity": "medium", "module": "repo_settings",
             "field": "allow_auto_merge", "actual": None},
        ],
    )
    proc = enforce(workdir)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 1, out
    # named as a permission problem to investigate...
    assert f"lost admin visibility on: {NO_ADMIN}" in out
    # ...and NOT excused as "go provision a token"
    assert "provision HYPEPROOF_GOVERNANCE_TOKEN" not in out
    # ...and the healthy repo's real finding still reaches the human
    assert "1 trustworthy governance drift finding" in out


def test_partial_blindness_never_suppresses_the_readable_repos(workdir):
    seed(
        workdir,
        f"ok {HARNESS}\nshallow a/b\nshallow c/d\nunreachable e/f\n",
        [{"repo": HARNESS, "severity": "critical", "module": "security", "field": "x"}],
    )
    out = enforce(workdir).stdout + enforce(workdir).stderr
    assert "1 trustworthy governance drift finding" in out
    assert "provision HYPEPROOF_GOVERNANCE_TOKEN" not in out


# --------------------------------------------------------- the other verdicts ----


def test_a_wholly_blind_run_is_the_only_credential_verdict(workdir):
    seed(workdir, "shallow a/b\nunreachable c/d\n", [])
    proc = enforce(workdir)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1, out
    assert "every policy repo is blind" in out
    assert "provision HYPEPROOF_GOVERNANCE_TOKEN" in out


def test_a_clean_run_passes(workdir):
    seed(workdir, f"ok {HARNESS}\n", [])
    proc = enforce(workdir, status="0")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "no governance drift" in proc.stdout


def test_a_run_that_classified_nothing_fails(workdir):
    """Non-vacuity. A control that examined nothing has not passed."""
    seed(workdir, "", [])
    proc = enforce(workdir, status="0")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "examined nothing" in proc.stdout + proc.stderr


def test_a_missing_audit_status_fails_instead_of_passing(workdir):
    """The original fail-open shape: audit did not run, job reported success.

    Kept as a defence even though the audit now always runs — a future preflight
    could fail for some other reason, and the answer would still be that an
    audit which did not run is not an all-clear.
    """
    seed(workdir, f"ok {HARNESS}\n", [])
    proc = enforce(workdir, status="")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "did not record an exit status" in proc.stdout + proc.stderr


def test_an_invalid_policy_is_named_as_a_policy_error(workdir):
    seed(workdir, f"ok {HARNESS}\n", [])
    proc = enforce(workdir, status="4")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1, out
    assert "policy error, not drift" in out


# ------------------------------------------------------------- classification ----


def _gh_authenticated() -> bool:
    try:
        return subprocess.run(["gh", "auth", "status"], capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


# Every other test in this file is offline and always runs. This one calls the
# GitHub API because that is the behaviour under test, so it skips rather than
# failing spuriously where `gh` has no token.
@pytest.mark.skipif(not _gh_authenticated(), reason="needs an authenticated gh CLI")
def test_classification_step_never_aborts_the_audit(workdir):
    """It classifies; it does not decide. Deciding here is what silenced the
    audit before."""
    (workdir / "preflight-repos.txt").write_text(f"{HARNESS}\n{NO_ADMIN}\n", encoding="utf-8")
    proc = run_step(AUDIT_STEPS["Classify repo visibility"], workdir)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    classified = (workdir / "preflight-classification.txt").read_text(encoding="utf-8")
    assert f"ok {HARNESS}" in classified
    assert f"shallow {NO_ADMIN}" in classified


def test_the_audit_step_has_no_exit_0_swallow():
    """Guards the specific line that made this job green while it was drifting."""
    run_audit = AUDIT_STEPS["Run live audit"]
    assert "exit 0" not in run_audit, "the audit step must not discard audit.py's exit code"
    assert "$GITHUB_OUTPUT" in run_audit, "the exit code must be recorded for the Enforce step"


def test_reports_survive_a_red_run():
    """The report is what the human acts on; it must outlive the failure that
    summons them."""
    spec = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["audit"]
    by_name = {s.get("name"): s for s in spec["steps"]}
    for name in ("Write summary", "Upload audit artifact", "Enforce"):
        assert by_name[name].get("if") == "always()", f"{name} must run on a red audit"


def test_weekly_loop_gate_did_not_inherit_the_fail_open_pattern():
    """Same file, newer job. Its Enforce must NOT be `if: always()` — the steps
    before it are hard preconditions, and a failure there must fail the job."""
    spec = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["weekly-loop-gate"]
    by_name = {s.get("name"): s for s in spec["steps"]}
    assert "if" not in by_name["Enforce"]
    assert "exit 0" not in GATE_STEPS["Enforce"]


def test_weekly_loop_gate_reports_distinct_issues_not_just_occurrences():
    """An issue labelled for two cycles is audited once per cycle. Reporting the
    occurrence count alone reads as two separate problems."""
    for step in ("Write violation report", "Enforce"):
        assert "distinct" in GATE_STEPS[step], f"{step} must disambiguate the count"
