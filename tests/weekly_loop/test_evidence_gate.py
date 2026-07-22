"""Evidence gate — cutoff, exemption codes, quoting bypasses, enforcement.

Companion to test_weekly_loop.py, which covers the original Owner/ETA and
evidence-shape rules. Everything here is a control the gate must actually
exercise, so the module ends with a non-vacuity test that asserts exact
injected-vs-detected counts against a committed adversarial corpus.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from test_weekly_loop import CHECK, PR_URL, REPO, fixture, run

CORPUS = Path(__file__).resolve().parent / "fixtures" / "evidence_corpus.json"
CORPUS_REPO = "jayleekr/hypeproof-corpus"
CORPUS_CYCLE = "weekly-2026-07-27"
CYCLE = "weekly-2026-07-21"

PRE_CUTOFF = "2026-07-21T12:37:36Z"   # 2026-07-21 21:37 KST
AT_CUTOFF = "2026-07-21T15:00:00Z"    # exactly 2026-07-22T00:00:00+09:00
POST_CUTOFF = "2026-07-22T03:00:00Z"  # 2026-07-22 12:00 KST


def _load_check():
    spec = importlib.util.spec_from_file_location("weekly_check", CHECK)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


check_mod = _load_check()


def closed(number: int, title: str, **extra: object) -> dict:
    issue = {"number": number, "title": title, "state": "CLOSED", "body": "",
             "closedAt": POST_CUTOFF}
    issue.update(extra)
    return issue


# ---------------------------------------------------------------- cutoff ----
# The exemption for historical work is derived from GitHub's closedAt, never
# from a label — a label-based exemption is one anyone can grant themselves.


def test_issue_closed_before_the_cutoff_is_exempt(tmp_path: Path) -> None:
    fx = fixture(tmp_path, [closed(40, "Old work", closedAt=PRE_CUTOFF, body="다 했음")])
    proc = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "before the 2026-07-22T00:00:00+09:00 cutoff" in proc.stdout
    assert "closed exempt, pre-cutoff:      1" in proc.stdout


def test_issue_closed_at_the_cutoff_instant_is_enforced(tmp_path: Path) -> None:
    fx = fixture(tmp_path, [closed(41, "Boundary", closedAt=AT_CUTOFF, body="다 했음")])
    proc = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "closed with no 'Evidence:' ref" in proc.stdout


def test_missing_close_timestamp_fails_closed(tmp_path: Path) -> None:
    # An unknown close time is not an exemption: absence of proof of exemption
    # must never behave like proof of exemption.
    fx = fixture(tmp_path, [{"number": 42, "title": "No closedAt", "state": "CLOSED",
                             "body": "완료"}])
    proc = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "close timestamp unavailable" in proc.stdout


def test_unparseable_close_timestamp_fails_closed(tmp_path: Path) -> None:
    fx = fixture(tmp_path, [closed(43, "Garbage closedAt", closedAt="yesterday")])
    proc = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "close timestamp unavailable" in proc.stdout


def test_no_label_can_buy_a_pre_cutoff_exemption(tmp_path: Path) -> None:
    fx = fixture(
        tmp_path,
        [closed(44, "Label-shopped", labels=[{"name": "no-evidence-needed"},
                                             {"name": "pre-cutoff"},
                                             {"name": "legacy"}])],
    )
    proc = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "closed exempt, pre-cutoff:      0" in proc.stdout


# ------------------------------------------------------- exemption codes ----


@pytest.mark.parametrize("code", ["cancelled", "duplicate", "administrative", "no-deliverable"])
def test_each_enumerated_exemption_code_is_accepted(tmp_path: Path, code: str) -> None:
    fx = fixture(tmp_path, [closed(45, f"Exempt {code}", body=f"Evidence-Exemption: {code}")])
    proc = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "EXEMPT" in proc.stdout


@pytest.mark.parametrize(
    "text",
    [
        "Evidence-Exemption: 그냥 필요 없습니다",
        "Evidence-Exemption: wontfix",
        "Evidence-Exemption: administrative — 라벨만 바꿈",  # trailing prose is not the code
        "Evidence-Exemption: n/a",
    ],
)
def test_free_form_exemption_text_is_rejected(tmp_path: Path, text: str) -> None:
    fx = fixture(tmp_path, [closed(46, "Free-form exemption", body=text)])
    proc = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "unknown Evidence-Exemption code" in proc.stdout


def test_exemption_code_inside_a_fence_does_not_exempt(tmp_path: Path) -> None:
    fx = fixture(
        tmp_path,
        [closed(47, "Quoted exemption", body="```\nEvidence-Exemption: cancelled\n```\n")],
    )
    proc = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "closed with no 'Evidence:' ref" in proc.stdout


# ------------------------------------------------ quoting-bypass coverage ----
# One test per quoting construct, for the evidence gate.


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("fenced", f"```\nEvidence: {PR_URL}\n```\n"),
        ("tilde-fenced", f"~~~markdown\nEvidence: {PR_URL}\n~~~\n"),
        ("indented", f"설명.\n\n    Evidence: {PR_URL}\n"),
        ("tab-indented", f"설명.\n\n\tEvidence: {PR_URL}\n"),
        ("inline", f"형식: `Evidence: {PR_URL}`\n"),
        ("html-comment", f"<!-- Evidence: {PR_URL} -->\n"),
        ("multiline-html-comment", f"<!--\nEvidence: {PR_URL}\n-->\n"),
        ("blockquote", f"> Evidence: {PR_URL}\n"),
    ],
)
def test_evidence_inside_quoted_regions_never_satisfies_the_gate(
    tmp_path: Path, name: str, body: str
) -> None:
    fx = fixture(tmp_path, [closed(50, f"Quoted via {name}", body=body)])
    proc = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx)
    assert proc.returncode == 1, f"{name}: {proc.stdout}{proc.stderr}"
    assert "closed with no 'Evidence:' ref" in proc.stdout


def test_evidence_after_a_closed_html_comment_still_counts(tmp_path: Path) -> None:
    # over-stripping guard: the comment must not swallow the rest of the body
    body = f"<!-- 내부 메모 -->\n\nEvidence: {PR_URL}\n"
    fx = fixture(tmp_path, [closed(51, "Comment then real ref", body=body)])
    proc = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx)
    assert proc.returncode == 0, proc.stdout + proc.stderr


# ------------------------------------- Owner/ETA quoting bypass (M003 fix) ----


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("fenced", "Owner: @jay\n\n```\nETA: 2026-07-20\n```\n"),
        ("indented", "Owner: @jay\n\n    ETA: 2026-07-20\n"),
        ("inline", "Owner: @jay\n\n`ETA: 2026-07-20`\n"),
        ("html-comment", "Owner: @jay\n\n<!--\nETA: 2026-07-20\n-->\n"),
        ("blockquote", "Owner: @jay\n\n> ETA: 2026-07-20\n"),
        ("eta-heading-in-fence", "Owner: @jay\n\n```\n## ETA\n2026-07-20\n```\n"),
    ],
)
def test_eta_inside_quoted_regions_does_not_satisfy_the_open_rule(
    tmp_path: Path, name: str, body: str
) -> None:
    fx = fixture(tmp_path, [{"number": 60, "title": f"Quoted ETA via {name}", "body": body}])
    proc = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx)
    assert proc.returncode == 1, f"{name}: {proc.stdout}{proc.stderr}"
    assert "missing 'ETA:' line" in proc.stdout


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("fenced", "ETA: 2026-07-20\n\n```\nOwner: @jay\n```\n"),
        ("indented", "ETA: 2026-07-20\n\n    Owner: @jay\n"),
        ("html-comment", "ETA: 2026-07-20\n\n<!-- ## Owner -->\n"),
        ("blockquote", "ETA: 2026-07-20\n\n> Owner: @jay\n"),
    ],
)
def test_owner_inside_quoted_regions_does_not_satisfy_the_open_rule(
    tmp_path: Path, name: str, body: str
) -> None:
    fx = fixture(tmp_path, [{"number": 61, "title": f"Quoted owner via {name}", "body": body}])
    proc = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx)
    assert proc.returncode == 1, f"{name}: {proc.stdout}{proc.stderr}"
    assert "missing 'Owner'/담당 section" in proc.stdout


def test_real_owner_eta_still_passes_next_to_a_quoted_template(tmp_path: Path) -> None:
    # the fix must reject quoted markers without rejecting real ones
    body = (
        "## Owner\n\n담당: @TJ-kr\n\nETA: 2026-07-20\n\n"
        "템플릿 참고:\n\n```\nOwner: <@handle>\nETA: 2099-01-01\n```\n"
    )
    fx = fixture(tmp_path, [{"number": 62, "title": "Real plus quoted", "body": body}])
    proc = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "2099" not in proc.stdout


# --------------------------------------------- existence vs syntax states ----


def test_github_linked_and_syntax_valid_are_reported_separately(tmp_path: Path) -> None:
    fx = fixture(
        tmp_path,
        [
            closed(70, "Typed ref only", body=f"Evidence: {PR_URL}"),
            closed(71, "Typed ref matching GitHub's record", body=f"Evidence: {PR_URL}",
                   closedByPullRequestsReferences=[{"number": 42, "url": PR_URL}]),
            closed(72, "GitHub record, no typed marker", body="완료",
                   closedByPullRequestsReferences=[
                       {"number": 43, "url": "https://github.com/jayleekr/sediment/pull/43"}]),
        ],
    )
    proc = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "syntax_valid, existence_unverified" in proc.stdout
    assert "existence verified by GitHub" in proc.stdout
    assert "evidence github-linked:         2" in proc.stdout
    assert "evidence syntax_valid:          1" in proc.stdout


# -------------------------------------------------- enforcement behaviour ----


@pytest.mark.parametrize("var", ["CI", "GITHUB_ACTIONS", "HYPEPROOF_ENFORCE"])
def test_skip_evidence_gate_is_refused_on_enforcement_paths(tmp_path: Path, var: str) -> None:
    fx = fixture(tmp_path, [closed(80, "No evidence", body="끝.")])
    proc = run(
        CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx,
        "--skip-evidence-gate", env={var: "true"},
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "--skip-evidence-gate is refused" in proc.stderr
    assert var in proc.stderr


def test_examining_nothing_fails_under_enforcement(tmp_path: Path) -> None:
    # M002's headline finding: a scanner that returns green after examining
    # (almost) nothing. Under CI an empty result set is an error, not a pass.
    fx = fixture(tmp_path, [])
    proc = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx,
               env={"CI": "true"})
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "A control that examined nothing has not passed" in proc.stderr


def test_min_issues_threshold_is_enforced(tmp_path: Path) -> None:
    fx = fixture(tmp_path, [closed(81, "One clean issue", body=f"Evidence: {PR_URL}")])
    ok = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx, "--min-issues", "1")
    assert ok.returncode == 0, ok.stdout + ok.stderr
    short = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx,
                "--min-issues", "5")
    assert short.returncode == 2, short.stdout + short.stderr
    assert "below --min-issues 5" in short.stderr


def test_json_report_carries_counts_and_per_issue_status(tmp_path: Path) -> None:
    fx = fixture(
        tmp_path,
        [
            closed(90, "Clean", body=f"Evidence: {PR_URL}"),
            closed(91, "Dirty", body="완료"),
        ],
    )
    proc = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx, "--json")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    report = json.loads(proc.stdout)
    assert report["counts"]["issues_examined"] == 2
    assert report["counts"]["violations_detected"] == 1
    assert report["counts"]["clean_accepted"] == 1
    statuses = {item["number"]: item["status"] for item in report["issues"]}
    assert statuses == {90: "ok_syntax_valid", 91: "violation"}


@pytest.mark.parametrize("issues", [[], [{"number": 92, "title": "Clean", "state": "CLOSED",
                                          "closedAt": POST_CUTOFF,
                                          "body": f"Evidence: {PR_URL}"}]])
def test_json_stdout_stays_parseable_when_there_are_no_violations(
    tmp_path: Path, issues: list
) -> None:
    # The live workflow parses this stdout. A human-readable trailer leaking
    # into it turns the whole scheduled audit into a hard error.
    fx = fixture(tmp_path, issues)
    proc = run(CHECK, "--cycle", CYCLE, "--repo", REPO, "--issues-json", fx, "--json")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    json.loads(proc.stdout)  # raises if anything else was written to stdout


# ------------------------------------------------------------ pagination ----


def test_gh_cycle_issues_escalates_the_limit_instead_of_truncating(monkeypatch) -> None:
    # `gh issue list --limit N` silently returns a prefix. A full page is not
    # proof that the page was the whole set, so the fetcher must ask again.
    requested: list[int] = []
    total = 250

    def fake_page(repo: str, label: str, limit: int) -> list[dict]:
        requested.append(limit)
        return [{"number": i} for i in range(min(limit, total))]

    monkeypatch.setattr(check_mod, "_gh_issue_page", fake_page)
    issues = check_mod.gh_cycle_issues("owner/name", "weekly-2026-07-21")
    assert requested == [200, 800]
    assert len(issues) == total


def test_gh_cycle_issues_refuses_a_possibly_truncated_set(monkeypatch) -> None:
    def always_full(repo: str, label: str, limit: int) -> list[dict]:
        return [{"number": i} for i in range(limit)]

    monkeypatch.setattr(check_mod, "_gh_issue_page", always_full)
    with pytest.raises(RuntimeError, match="refusing to report on a partial issue set"):
        check_mod.gh_cycle_issues("owner/name", "weekly-2026-07-21")


# ---------------------------------------------------------- non-vacuity ----


CORPUS_EXPECTED = {
    "repos_examined": 1,
    "issues_examined": 35,
    "open_examined": 9,
    "closed_examined": 26,
    "comments_examined": 3,
    "violations_detected": 19,   # injected violations, all of which must be caught
    "clean_accepted": 16,        # expected-clean cases, all of which must pass
    "exempt_pre_cutoff": 2,
    "exempt_not_planned": 1,
    "exempt_code": 4,
    "ok_github_linked": 2,
    "ok_syntax_valid": 5,
}


def test_adversarial_corpus_detects_every_injected_violation() -> None:
    """Non-vacuity proof: exact injected-vs-detected counts on a fixed corpus.

    Every issue in fixtures/evidence_corpus.json is labelled 'V ' (a violation
    deliberately injected) or 'C ' (an expected-clean case). The gate must
    catch all of the first group and accept all of the second — a run that
    examines nothing, or that quietly stops detecting one bypass, fails here.
    """
    proc = run(CHECK, "--cycle", CORPUS_CYCLE, "--repo", CORPUS_REPO,
               "--issues-json", str(CORPUS), "--json")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    report = json.loads(proc.stdout)

    assert report["counts"] == {**report["counts"], **CORPUS_EXPECTED}, report["counts"]

    injected = {i["number"] for i in report["issues"] if i["number"] < 200}
    clean = {i["number"] for i in report["issues"] if i["number"] >= 200}
    detected = {i["number"] for i in report["issues"] if i["status"] == "violation"}
    assert detected == injected, f"missed: {injected - detected}, false: {detected - injected}"
    assert not (clean & detected), f"false positives on expected-clean: {clean & detected}"
    assert len(injected) == 19 and len(clean) == 16
