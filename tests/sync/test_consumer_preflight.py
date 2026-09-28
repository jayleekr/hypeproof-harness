"""sync.sh must not write into a consumer checkout that is stale or busy.

Sync used to write into whatever each consumer had checked out. On 2026-09-28
that left studio (54 behind origin/main), sediment (8 behind) and lab (on a
feature branch) with working trees older than their own origin/main, mixed into
unrelated work. These tests pin the pre-flight: every consumer is checked before
any is written, and writes land on a sync/harness-<sha7> branch cut from
origin/main. Everything runs against temporary repos; no network.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from _platform import BASH


ROOT = Path(__file__).resolve().parents[2]
SYNC = ROOT / "scripts/sync.sh"
HARNESS_SHA = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
SYNC_BRANCH = f"sync/harness-{HARNESS_SHA[:7]}"
VENDORED = Path(".claude/skills/hype-pr/SKILL.md")


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def _commit(repo: Path, message: str) -> None:
    git(repo, "-c", "user.email=t@example.invalid", "-c", "user.name=T", "commit", "-qm", message)


@pytest.fixture
def consumers() -> list[str]:
    names = []
    for line in (ROOT / "tests/consumers.txt").read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.append(line.rsplit("/", 1)[-1])
    assert names
    return names


@pytest.fixture
def workspace(tmp_path, consumers) -> Path:
    """Each consumer: a bare origin with one commit, cloned on main."""
    ws = tmp_path / "ws"
    for name in consumers:
        seed = tmp_path / "seed" / name
        seed.mkdir(parents=True)
        git(seed, "init", "-qb", "main")
        (seed / "README.md").write_text("consumer\n")
        git(seed, "add", "-A")
        _commit(seed, "init")
        bare = tmp_path / "origins" / f"{name}.git"
        subprocess.check_call(["git", "clone", "-q", "--bare", str(seed), str(bare)])
        subprocess.check_call(["git", "clone", "-q", str(bare), str(ws / name)])
        # sync.sh --commit uses the consumer's own identity; CI has no global one.
        git(ws / name, "config", "user.email", "t@example.invalid")
        git(ws / name, "config", "user.name", "T")
    return ws


def run_sync(ws: Path, *args: str, **env: str) -> subprocess.CompletedProcess:
    full_env = {k: v for k, v in os.environ.items() if not k.startswith("CONSUMER_")}
    full_env.pop("ALLOW_ANY_BRANCH", None)
    full_env.update(HYPEPROOF_WORKSPACE=str(ws), **env)
    # A developer-local consumer list would point sync at real checkouts.
    assert not (ROOT / "tests/consumers.local.txt").exists(), "move tests/consumers.local.txt aside"
    return subprocess.run([BASH, str(SYNC), *args], cwd=ROOT, env=full_env,
                          capture_output=True, text=True)


def advance_origin(ws: Path, name: str) -> None:
    """Someone else merged to origin/main after this clone was made."""
    other = ws.parent / f"{name}.other"
    subprocess.check_call(["git", "clone", "-q", git(ws / name, "remote", "get-url", "origin"), str(other)])
    (other / "NEW.md").write_text("new\n")
    git(other, "add", "-A")
    _commit(other, "newer")
    git(other, "push", "-q", "origin", "main")


def test_clean_consumers_are_synced_on_a_fresh_branch_from_origin_main(workspace, consumers):
    proc = run_sync(workspace)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for name in consumers:
        repo = workspace / name
        assert git(repo, "symbolic-ref", "--short", "HEAD") == SYNC_BRANCH
        assert git(repo, "rev-parse", "HEAD") == git(repo, "rev-parse", "origin/main")
        assert (repo / VENDORED).is_file()
        assert f"BRANCH {name}" in proc.stdout
    # Re-running on the branch it created is a no-op, not a refusal.
    again = run_sync(workspace)
    assert again.returncode == 0, again.stdout + again.stderr


def test_a_consumer_behind_origin_main_aborts_before_anything_is_written(workspace, consumers):
    stale = consumers[-1]
    advance_origin(workspace, stale)

    proc = run_sync(workspace)
    assert proc.returncode == 4, proc.stdout + proc.stderr
    assert "behind origin/main" in proc.stderr
    assert "pull --ff-only" in proc.stderr
    for name in consumers:  # including the ones checked before the stale one
        repo = workspace / name
        assert not (repo / VENDORED).exists()
        assert git(repo, "symbolic-ref", "--short", "HEAD") == "main"


def test_a_consumer_on_a_feature_branch_is_refused(workspace, consumers):
    busy = workspace / consumers[0]
    git(busy, "switch", "-qc", "fix/some-work")

    proc = run_sync(workspace)
    assert proc.returncode == 4, proc.stdout + proc.stderr
    assert "fix/some-work" in proc.stderr and "switch main" in proc.stderr
    assert not (busy / VENDORED).exists()
    assert git(busy, "symbolic-ref", "--short", "HEAD") == "fix/some-work"


def test_changes_outside_vendored_paths_are_refused(workspace, consumers):
    repo = workspace / consumers[0]
    (repo / "README.md").write_text("local edit\n")

    proc = run_sync(workspace)
    assert proc.returncode == 5, proc.stdout + proc.stderr
    assert "README.md" in proc.stderr
    assert not (repo / VENDORED).exists()


def test_leftovers_in_vendored_paths_are_overwritten(workspace, consumers):
    """The residue of an earlier sync is exactly what a new sync replaces."""
    repo = workspace / consumers[0]
    (repo / VENDORED).parent.mkdir(parents=True)
    (repo / VENDORED).write_text("stale vendored copy\n")

    proc = run_sync(workspace)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (repo / VENDORED).read_bytes() == (ROOT / "skills/hype-pr/SKILL.md").read_bytes()


def test_commit_mode_commits_on_the_sync_branch_and_leaves_main_alone(workspace, consumers):
    proc = run_sync(workspace, "--commit")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for name in consumers:
        repo = workspace / name
        assert git(repo, "rev-parse", "main") == git(repo, "rev-parse", "origin/main")
        assert int(git(repo, "rev-list", "--count", f"main..{SYNC_BRANCH}")) > 0
        assert git(repo, "status", "--porcelain") == ""


def test_allow_any_branch_applies_in_place_but_never_on_a_stale_base(workspace, consumers):
    busy = workspace / consumers[0]
    git(busy, "switch", "-qc", "fix/some-work")

    proc = run_sync(workspace, ALLOW_ANY_BRANCH="1")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert git(busy, "symbolic-ref", "--short", "HEAD") == "fix/some-work"
    assert (busy / VENDORED).is_file()

    advance_origin(workspace, consumers[0])
    proc = run_sync(workspace, ALLOW_ANY_BRANCH="1")
    assert proc.returncode == 4, proc.stdout + proc.stderr
    assert "behind origin/main" in proc.stderr


def test_local_only_repos_are_applied_in_place(tmp_path, consumers):
    """CI's mock consumers have no origin; they keep the old in-place apply."""
    ws = tmp_path / "ws"
    for name in consumers:
        repo = ws / name
        repo.mkdir(parents=True)
        git(repo, "init", "-qb", "main")
        (repo / "scratch.txt").write_text("untracked is fine without a remote\n")
    proc = run_sync(ws)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for name in consumers:
        assert (ws / name / VENDORED).is_file()
        assert git(ws / name, "symbolic-ref", "--short", "HEAD") == "main"
