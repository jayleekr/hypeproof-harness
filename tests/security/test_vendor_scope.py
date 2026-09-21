from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from _platform import BASH


ROOT = Path(__file__).resolve().parents[2]
SYNC = ROOT / "scripts" / "sync.sh"
README = ROOT / "README.md"


def _array(name: str) -> str:
    """Return the raw contents of a top-level bash array in sync.sh."""
    text = SYNC.read_text(encoding="utf-8")
    return text.split(f"{name}=(", 1)[1].split(")", 1)[0]


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True
    ).strip()


def _consumer(root: Path, name: str) -> Path:
    path = root / name
    path.mkdir(parents=True)
    _git(path, "init", "-qb", "main")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Fixture")
    _git(path, "commit", "--allow-empty", "-qm", "init")
    return path


def test_security_is_vendored_as_a_file_not_as_a_tree() -> None:
    """harness ships one file into scripts/security/; consumers own the rest.

    SCRIPTS claims a whole directory with `rsync --delete`, which aborts the
    sync for any consumer that keeps its own files there (#209). A single file
    belongs in SCRIPT_FILES instead.
    """
    assert "security" not in _array("SCRIPTS").split()
    assert "security/check-secrets.sh" in _array("SCRIPT_FILES").split()


def test_readme_records_security_as_file_level_vendoring() -> None:
    """The deployment table is the canon for what is vendored where.

    A PR that moves a path between SCRIPTS and SCRIPT_FILES must move the
    table with it, or the table silently starts lying.
    """
    rows = [
        line
        for line in README.read_text(encoding="utf-8").splitlines()
        if line.startswith("|") and "scripts/security" in line
    ]
    assert len(rows) == 1, f"expected exactly one scripts/security row, got {rows}"
    assert "check-secrets.sh" in rows[0]
    assert "3 consumers `scripts/security/`" not in rows[0]


@pytest.mark.parametrize("mode", ["apply", "check"])
def test_sync_keeps_consumer_owned_files_next_to_a_vendored_file(tmp_path, mode) -> None:
    """The real hypeprooflab shape: lab-owned scanners in scripts/security/.

    Before #209 this aborted the whole consumer with `exit 3`, so lab never
    received scripts/ or docs/ at all.
    """
    workspace = tmp_path / "ws"
    workspace.mkdir()
    lab = _consumer(workspace, "hypeprooflab")
    owned = lab / "scripts/security"
    owned.mkdir(parents=True)
    for name in ("scan_public_email_pii.py", "verify_oauth_purge.py", "README.md"):
        (owned / name).write_text(f"# lab-owned {name}\n")
    # Left behind by the era when this path was vendored as a whole tree.
    (owned / "HARNESS_VERSION").write_text("deadbeef\n")
    _git(lab, "add", "-A")
    _git(lab, "commit", "-qm", "lab security scripts")

    # Every consumer in tests/consumers.txt must resolve, or sync.sh reports a
    # skip and exits non-zero for reasons unrelated to what this test asserts.
    for name in ("hypeproof-studio", "sediment"):
        _consumer(workspace, name)

    args = [BASH, str(SYNC)] + (["--check"] if mode == "check" else [])
    proc = subprocess.run(
        args,
        cwd=ROOT,
        env={
            "PATH": os.environ["PATH"],
            "HOME": os.environ.get("HOME", str(tmp_path)),
            "HYPEPROOF_WORKSPACE": str(workspace),
        },
        capture_output=True,
        text=True,
    )
    assert "ABORT" not in proc.stdout + proc.stderr, proc.stdout + proc.stderr

    if mode == "apply":
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert (owned / "check-secrets.sh").is_file()
        for name in ("scan_public_email_pii.py", "verify_oauth_purge.py", "README.md"):
            assert (owned / name).read_text() == f"# lab-owned {name}\n"
        # The stamp described a tree this path no longer is.
        assert not (owned / "HARNESS_VERSION").exists()
        # Inside the shared directory, only harness-owned paths moved. The rest
        # of the sync (docs, skills, other script trees) is out of scope here.
        changed = {
            line.split()[-1]
            for line in _git(
                lab, "status", "--porcelain", "--", "scripts/security"
            ).splitlines()
        }
        assert changed == {
            "scripts/security/check-secrets.sh",
            "scripts/security/HARNESS_VERSION",
        }, changed
