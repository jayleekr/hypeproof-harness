"""The Python dependencies harness tooling needs must be declared and installable.

Before #220 the only declaration lived in `skills/hype-pr/SKILL.md` — an
agent-facing file, with no manifest to install from. Every CI workflow installed
PyYAML inline, so CI was self-sufficient and never surfaced the gap, while a
person running the same command locally hit a bare `PyYAML is required`.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "requirements.txt"
DEV = ROOT / "requirements-dev.txt"
WORKFLOWS = sorted((ROOT / ".github/workflows").glob("*.yml"))


def test_runtime_manifest_declares_the_import_that_actually_fails() -> None:
    assert RUNTIME.is_file(), "harness needs a runtime dependency manifest"
    assert re.search(r"^pyyaml\b", RUNTIME.read_text(), re.M | re.I), RUNTIME.read_text()


def test_dev_manifest_builds_on_the_runtime_one() -> None:
    text = DEV.read_text()
    assert "-r requirements.txt" in text, "dev deps must include the runtime set"
    assert re.search(r"^pytest\b", text, re.M | re.I), text


def test_ci_installs_from_the_manifests_instead_of_inline_package_lists() -> None:
    """An inline `pip install pyyaml` makes CI self-sufficient and hides the gap.

    Keeping CI on the manifests means a dependency that is added for a script
    but forgotten in requirements.txt breaks CI, which is the point.
    """
    offenders = []
    for workflow in WORKFLOWS:
        for number, line in enumerate(workflow.read_text().splitlines(), 1):
            if "pip install" not in line:
                continue
            if "-r requirements" in line:
                continue
            offenders.append(f"{workflow.relative_to(ROOT)}:{number}: {line.strip()}")
    assert not offenders, "install from the manifests:\n" + "\n".join(offenders)


def test_the_yaml_guard_names_the_interpreter_and_the_manifest() -> None:
    """`python3 -m pip install pyyaml` sends people to the wrong environment.

    pr.py re-execs into the canonical harness checkout, so the interpreter that
    fails is often not the one the reader would type.
    """
    guard = (ROOT / "scripts/repo-governance/audit.py").read_text()
    block = guard.split("except ImportError", 1)[1].split("\n\n", 1)[0]
    assert "sys.executable" in block, block
    assert "requirements.txt" in block, block


def test_consumers_do_not_vendor_the_manifests() -> None:
    """Dependencies belong to the harness checkout, not to consumer copies.

    pr.py delegates to the canonical checkout and imports yaml from
    scripts/repo-governance/, which is not vendored — so a consumer-side
    manifest cannot satisfy it.
    """
    sync = (ROOT / "scripts/sync.sh").read_text()
    for name in ("requirements.txt", "requirements-dev.txt"):
        assert name not in sync, f"{name} must not be vendored to consumers"
