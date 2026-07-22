"""verify_pr_closes.py — a PR close ref must name an issue that actually exists.

The control this replaces was a pure regex: `grep -qE '(Closes|Fixes|Resolves)
 #[0-9]+'`, which passed `Closes #999999` and `Fixes #0` — form without
existence. Every test here drives the offline resolver (`--refs-json`, a
{"<n>": true|false} table) so it is deterministic and needs neither gh nor the
network; an absent key means "unknown", which must fail closed, never pass.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERIFY = ROOT / "scripts" / "weekly-harness" / "verify_pr_closes.py"
REPO = "jayleekr/hypeproof-harness"


def run(body: str, table: dict, *extra: str) -> subprocess.CompletedProcess[str]:
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(table, fh)
        refs = fh.name
    return subprocess.run(
        [sys.executable, str(VERIFY), "--repo", REPO, "--body", body,
         "--refs-json", refs, *extra],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )


def test_no_close_ref_is_rejected() -> None:
    proc = run("Just some prose, no ref.", {})
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "must include 'Closes #<n>'" in proc.stderr


def test_a_real_issue_reference_passes() -> None:
    proc = run("Fixes #12 by rewiring the gate.", {"12": True})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "1 close ref(s) resolved" in proc.stdout + proc.stderr


def test_nonexistent_high_number_is_rejected() -> None:
    # The headline bypass: the old grep accepted this; existence must not.
    proc = run("Closes #999999", {"999999": False})
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "do not exist" in proc.stderr
    assert "#999999" in proc.stderr


def test_issue_zero_is_rejected() -> None:
    proc = run("Fixes #0", {"0": False})
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "#0" in proc.stderr


def test_one_missing_among_several_fails_and_is_named() -> None:
    proc = run("Closes #12, Resolves #13, Fixes #777", {"12": True, "13": True, "777": False})
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "#777" in proc.stderr
    assert "#12" not in proc.stderr.split("do not exist")[-1]


def test_unknown_ref_fails_closed_not_open() -> None:
    # Absent from the table => the resolver could not tell => exit 2, never a
    # silent pass. An unverifiable reference has not been verified.
    proc = run("Closes #55", {})
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "could not verify" in proc.stderr


def test_keywords_are_case_insensitive_and_deduped() -> None:
    proc = run("closes #7 and CLOSES #7 again", {"7": True}, "--json")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(proc.stdout)
    assert report["result"]["refs"] == [7]
    assert report["result"]["resolved"] == [7]


def test_report_carries_provenance() -> None:
    proc = run("Closes #12", {"12": True}, "--json")
    report = json.loads(proc.stdout)
    prov = report["provenance"]
    assert prov["repo"] == REPO
    assert prov["verifier_version"].startswith("sha256:")
    assert "operator" in prov and "environment" in prov


def test_bare_hash_without_keyword_is_not_a_close_ref() -> None:
    # `#12` alone (e.g. "see #12") is a mention, not a close directive.
    proc = run("Related to #12, but this PR closes nothing.", {"12": True})
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "must include 'Closes #<n>'" in proc.stderr
