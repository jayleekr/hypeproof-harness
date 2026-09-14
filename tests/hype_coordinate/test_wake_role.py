from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import call, patch

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "skills/hype-coordinate/scripts/wake_role.py"
SPEC = importlib.util.spec_from_file_location("hype_coordinate_wake_role", MODULE_PATH)
assert SPEC and SPEC.loader
WAKE_ROLE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = WAKE_ROLE
SPEC.loader.exec_module(WAKE_ROLE)


def surface():
    return WAKE_ROLE.Surface(
        workspace_ref="workspace:1",
        workspace_id="workspace-uuid",
        surface_ref="surface:2",
        surface_id="surface-uuid",
        title="codex-2",
    )


def test_send_types_then_submits_with_targeted_enter():
    with patch.object(WAKE_ROLE, "cmux") as cmux:
        WAKE_ROLE.send(surface(), "dispatch packet")

    target = ("--workspace", "workspace-uuid", "--surface", "surface-uuid")
    assert cmux.call_args_list == [
        call("send", *target, "--", "dispatch packet"),
        call("send-key", *target, "enter"),
    ]


def test_running_marker_proves_start():
    assert WAKE_ROLE.running_observed("Working (2s - esc to interrupt)")
    assert not WAKE_ROLE.running_observed("› dispatch packet")


def test_nonempty_codex_prompt_is_not_idle():
    screen = """
old output
› $hype-verify Coordinator dispatch packet packet-1.
  EnterEnter

  gpt-5.6-sol high
"""
    with pytest.raises(RuntimeError, match="unsent text"):
        WAKE_ROLE.assert_idle(screen)


def test_role_contracts_share_one_canonical_file():
    contract = ROOT / "skills/hype-coordinate/references/team-contract.md"
    assert contract.is_file()
    for role in ("hype-coordinate", "hype-intent", "hype-studio", "hype-chalk", "hype-verify", "hypeproof-operator"):
        canonical = ROOT / "skills" / role / "SKILL.md"
        assert canonical.is_file()
        assert (ROOT / ".agents" / "skills" / role / "SKILL.md").resolve() == canonical
        if role in ("hype-intent", "hype-studio", "hype-chalk", "hype-verify"):
            skill = canonical.read_text(encoding="utf-8")
            assert "(../hype-coordinate/references/team-contract.md)" in skill
