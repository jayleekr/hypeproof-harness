from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "identity-assert.sh"

EXPECTED_ACTOR = "hypeproof-automation"


def _make_gh_stub(dir_path: Path, *, login: str = "nobody", fail: bool = False) -> None:
    """Write a fake `gh` onto a dir we put first on PATH.

    The stub ignores its args and prints the configured login, so the guard's
    `gh api user --jq .login` resolves to a value we control. fail=True makes gh
    exit non-zero, simulating an unauthenticated / broken CLI (identity UNKNOWN).
    """
    gh = dir_path / "gh"
    body = "#!/usr/bin/env bash\n"
    if fail:
        body += "exit 7\n"
    else:
        body += f"printf '%s\\n' {login!r}\n"
    gh.write_text(body, encoding="utf-8")
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _run(
    tmp_path: Path,
    *,
    actor_env: str | None,
    gh_login: str = "nobody",
    gh_fail: bool = False,
    gh_present: bool = True,
    extra_args: list[str] | None = None,
    script: Path = SCRIPT,
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    if gh_present:
        _make_gh_stub(bin_dir, login=gh_login, fail=gh_fail)

    env = dict(os.environ)
    # Keep bash + coreutils reachable, but put our stub dir first so our gh wins.
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    env.pop("HYPEPROOF_AUTOMATION_ACTOR", None)
    if actor_env is not None:
        env["HYPEPROOF_AUTOMATION_ACTOR"] = actor_env
    # A token-shaped value that must never surface in the guard's output.
    env["GH_TOKEN"] = "ghp_" + "Z" * 36

    return subprocess.run(
        ["bash", str(script), *(extra_args or [])],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


# --- the four required control cases ---------------------------------------

def test_enforce_match_passes(tmp_path: Path) -> None:
    """enforce + actual == expected -> exit 0."""
    proc = _run(tmp_path, actor_env=EXPECTED_ACTOR, gh_login=EXPECTED_ACTOR)
    assert proc.returncode == 0, proc.stderr
    assert f"decision=pass" in proc.stdout
    assert f"mode=enforce" in proc.stdout


def test_enforce_mismatch_fails_closed(tmp_path: Path) -> None:
    """enforce + actual != expected -> non-zero (fail closed, no write)."""
    proc = _run(tmp_path, actor_env=EXPECTED_ACTOR, gh_login="jayleekr")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "decision=fail" in proc.stdout
    assert "FAIL CLOSED" in proc.stderr
    # self-report names both principals so green proves what it checked
    assert f"expected={EXPECTED_ACTOR}" in proc.stdout
    assert "actual=jayleekr" in proc.stdout


def test_warn_mode_unset_allows_and_logs(tmp_path: Path) -> None:
    """warn + env unset -> exit 0 + warning naming the actual principal."""
    proc = _run(tmp_path, actor_env=None, gh_login="jayleekr")
    assert proc.returncode == 0, proc.stderr
    assert "decision=warn" in proc.stdout
    assert "mode=warn" in proc.stdout
    assert "automation identity not provisioned" in proc.stderr
    assert "jayleekr" in proc.stderr


def test_enforce_unknown_identity_fails_closed(tmp_path: Path) -> None:
    """enforce + gh cannot resolve identity -> fail closed (can't prove => deny)."""
    proc = _run(tmp_path, actor_env=EXPECTED_ACTOR, gh_fail=True)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "decision=fail" in proc.stdout
    assert "actual=<unknown>" in proc.stdout


def test_enforce_gh_missing_fails_closed(tmp_path: Path) -> None:
    """enforce + gh not installed -> fail closed."""
    proc = _run(tmp_path, actor_env=EXPECTED_ACTOR, gh_present=False)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "actual=<unknown>" in proc.stdout


# --- the guard must never echo a token -------------------------------------

def test_no_token_value_in_output(tmp_path: Path) -> None:
    proc = _run(tmp_path, actor_env=EXPECTED_ACTOR, gh_login="jayleekr")
    token = "ghp_" + "Z" * 36
    assert token not in proc.stdout
    assert token not in proc.stderr


# --- mutation control: prove the fail-closed exit has teeth (not a no-op) ---

def test_mutation_removing_fail_flips_result(tmp_path: Path) -> None:
    """Copy the guard, mutate the deny so `fail` decisions become `pass`, and
    show the enforce-mismatch case — which exits 1 on the real guard — exits 0
    on the mutant. This proves the exit-1 is CAUSED by the guard's decision
    logic, i.e. the assertion actually bites and is not incidentally passing.
    """
    src = SCRIPT.read_text(encoding="utf-8")
    marker = 'DECISION="fail"'
    assert marker in src, "expected default-deny assignment not found"
    # Neuter the default-deny: every path now yields pass.
    mutant_src = src.replace(marker, 'DECISION="pass"')
    # Also neuter the explicit enforce mismatch branch.
    mutant_src = mutant_src.replace(
        "  else\n    DECISION=\"fail\"\n  fi",
        "  else\n    DECISION=\"pass\"\n  fi",
    )
    mutant = tmp_path / "identity-assert.mutant.sh"
    mutant.write_text(mutant_src, encoding="utf-8")

    # Real guard: mismatch -> exit 1.
    real = _run(tmp_path, actor_env=EXPECTED_ACTOR, gh_login="jayleekr")
    assert real.returncode == 1

    # Mutant: same inputs -> exit 0 (the deny was the only thing making it fail).
    mut = _run(
        tmp_path, actor_env=EXPECTED_ACTOR, gh_login="jayleekr", script=mutant
    )
    assert mut.returncode == 0, mut.stdout + mut.stderr
