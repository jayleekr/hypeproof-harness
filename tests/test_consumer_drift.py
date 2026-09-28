"""Real-consumer drift reporting must never read an unknown as a pass.

tests/run.sh and the `gate` CI job vendor into freshly created mock repos, so
they prove sync.sh works while saying nothing about the real consumers. That is
how skill-creator and notify sat four months stale in every consumer with CI
green (#208). This checker looks at the real ones — and one of them is private,
so partial coverage is the normal case and has to be reported as such.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from _platform import BASH


ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "scripts/consumer-drift/check.sh"

EXIT_CLEAN, EXIT_DRIFT, EXIT_UNREACHABLE, EXIT_USAGE = 0, 1, 2, 3


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def _origin(base: Path, name: str, *, vendored: bool) -> None:
    """Build a clonable repo that stands in for a consumer on GitHub."""
    work = base / f"{name}.work"
    work.mkdir(parents=True)
    _git(work, "init", "-qb", "main")
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "Fixture")
    (work / "README.md").write_text("consumer\n")

    if vendored:
        # A consumer that is current: run the real vendoring into it.
        subprocess.run(
            [BASH, str(ROOT / "scripts/sync.sh")],
            cwd=ROOT,
            env={
                **os.environ,
                "HYPEPROOF_WORKSPACE": str(base),
                f"CONSUMER_{name.replace('-', '_')}": str(work),
            },
            capture_output=True,
            text=True,
            check=False,
        )

    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "state")
    subprocess.check_output(
        ["git", "clone", "--quiet", "--bare", str(work), str(base / f"{name}.git")],
        text=True,
    )


def _run(workspace: Path, base: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [BASH, str(CHECK), "--workspace", str(workspace)],
        cwd=ROOT,
        env={
            "PATH": os.environ["PATH"],
            "HOME": os.environ.get("HOME", str(workspace)),
            "CONSUMER_GIT_BASE": str(base),
        },
        capture_output=True,
        text=True,
    )


@pytest.fixture
def consumers() -> list[str]:
    names = []
    for line in (ROOT / "tests/consumers.txt").read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.append(line.rsplit("/", 1)[-1])
    assert names
    return names


def test_a_stale_consumer_is_reported_as_drift(tmp_path, consumers) -> None:
    base = tmp_path / "origins"
    for name in consumers:
        _origin(base, name, vendored=False)

    proc = _run(tmp_path / "ws", base)
    assert proc.returncode == EXIT_DRIFT, proc.stdout + proc.stderr
    assert "DRIFT" in proc.stdout
    for name in consumers:
        assert f"CLONED       {name}" in proc.stdout


def test_a_consumer_that_cannot_be_read_is_not_counted_as_checked(
    tmp_path, consumers
) -> None:
    """The failure mode this guards: silence reading as health."""
    base = tmp_path / "origins"
    missing = consumers[-1]
    for name in consumers:
        if name != missing:
            _origin(base, name, vendored=True)

    proc = _run(tmp_path / "ws", base)
    assert proc.returncode == EXIT_UNREACHABLE, proc.stdout + proc.stderr
    assert f"UNREACHABLE  {missing}" in proc.stdout
    assert missing in proc.stdout.split("NOT checked:", 1)[1]
    # No drift among the ones we could read — but that must not exit 0.
    assert "DRIFT" not in proc.stdout


def test_every_consumer_unreachable_proves_nothing(tmp_path, consumers) -> None:
    base = tmp_path / "origins"
    base.mkdir(parents=True)

    proc = _run(tmp_path / "ws", base)
    assert proc.returncode == EXIT_UNREACHABLE, proc.stdout + proc.stderr
    assert "proves nothing" in proc.stdout + proc.stderr


def test_bad_usage_is_rejected(tmp_path) -> None:
    proc = subprocess.run(
        [BASH, str(CHECK), "--nonsense"],
        cwd=ROOT,
        env={"PATH": os.environ["PATH"], "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
    )
    assert proc.returncode == EXIT_USAGE


def test_workflow_does_not_block_pull_requests() -> None:
    """Drift is a state of the world, not a defect in the change under review."""
    workflow = (ROOT / ".github/workflows/consumer-drift.yml").read_text()
    trigger = workflow.split("on:", 1)[1].split("permissions:", 1)[0]
    assert "pull_request" not in trigger, trigger
    assert "schedule" in trigger and "workflow_dispatch" in trigger, trigger
