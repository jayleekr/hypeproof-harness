from __future__ import annotations

import importlib.util
import json
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


def test_send_waits_for_attempt_to_render_then_submits_with_targeted_enter():
    screens = iter(["idle", "› dispatch ATTEMPT_1"])
    with (
        patch.object(WAKE_ROLE, "cmux") as cmux,
        patch.object(
            WAKE_ROLE,
            "read_screen",
            side_effect=lambda *_args, **_kwargs: next(screens),
        ),
        patch.object(WAKE_ROLE.time, "monotonic", side_effect=[0.0, 0.0]),
    ):
        WAKE_ROLE.send(surface(), "dispatch ATTEMPT_1", "ATTEMPT_1", 1)

    target = ("--workspace", "workspace-uuid", "--surface", "surface-uuid")
    assert cmux.call_args_list == [
        call("send", *target, "--", "dispatch ATTEMPT_1"),
        call("send-key", *target, "enter"),
    ]


def test_historical_running_marker_does_not_prove_this_dispatch_started():
    assert WAKE_ROLE.running_observed("Working (2s - esc to interrupt)")
    assert not WAKE_ROLE.running_observed("› dispatch packet")
    screen = "Working (2s - esc to interrupt)\n› dispatch ATTEMPT_1"
    assert not WAKE_ROLE.running_observed_after(screen, "ATTEMPT_1")


def test_marker_specific_running_transition_proves_new_start():
    screen = (
        "old Working (2s - esc to interrupt)\n"
        "› dispatch ATTEMPT_1\n"
        "Working (1s - esc to interrupt)"
    )
    assert WAKE_ROLE.running_observed_after(screen, "ATTEMPT_1")


def test_send_never_presses_enter_when_text_did_not_render():
    with (
        patch.object(WAKE_ROLE, "cmux") as cmux,
        patch.object(
            WAKE_ROLE, "read_screen", return_value="› Ask Codex to do anything"
        ),
        patch.object(WAKE_ROLE.time, "sleep"),
        patch.object(WAKE_ROLE.time, "monotonic", side_effect=[0.0, 0.0, 2.0]),
    ):
        with pytest.raises(RuntimeError, match="Enter was not sent"):
            WAKE_ROLE.send(surface(), "dispatch ATTEMPT_1", "ATTEMPT_1", 1)

    assert (
        call(
            "send-key",
            "--workspace",
            "workspace-uuid",
            "--surface",
            "surface-uuid",
            "enter",
        )
        not in cmux.call_args_list
    )


def test_unsent_packet_is_cleared_and_never_reported_as_started():
    unsent = "old Working - esc to interrupt\n› dispatch ATTEMPT_1"
    screens = iter([unsent, unsent, "› Ask Codex to do anything"])
    with (
        patch.object(
            WAKE_ROLE,
            "read_screen",
            side_effect=lambda *_args, **_kwargs: next(screens),
        ),
        patch.object(WAKE_ROLE, "cancel_message") as cancel,
        patch.object(WAKE_ROLE.time, "sleep"),
        patch.object(
            WAKE_ROLE.time,
            "monotonic",
            side_effect=[0.0, 0.0, 2.0, 2.0, 2.0],
        ),
    ):
        with pytest.raises(RuntimeError, match="composer cleared"):
            WAKE_ROLE.wait_for_start(surface(), "ATTEMPT_1", 1)

    cancel.assert_called_once_with(surface())


def test_ordinary_dispatch_reports_pending_until_github_ack(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "wake_role.py",
            "--role",
            "x2",
            "--packet",
            "packet-171",
            "--work-url",
            "https://github.com/jayleekr/hypeproof-harness/issues/171",
            "--apply",
        ],
    )
    with (
        patch.object(WAKE_ROLE, "preflight_socket") as preflight,
        patch.object(WAKE_ROLE, "find_surface", return_value=surface()),
        patch.object(
            WAKE_ROLE, "read_screen", return_value="› Ask Codex to do anything"
        ),
        patch.object(WAKE_ROLE, "send") as send,
        patch.object(WAKE_ROLE, "wait_for_start") as wait_for_start,
    ):
        assert WAKE_ROLE.main() == 0

    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "submitted_pending_ack"
    assert result["accepted"] is False
    assert result["dispatch_attempt"].startswith("WAKE_ATTEMPT_X2_")
    preflight.assert_called_once_with()
    send.assert_called_once()
    wait_for_start.assert_called_once()


BROKEN_PIPE = "Error: Failed to write to socket (Broken pipe, errno 32)"


def test_socket_access_denial_is_reported_without_retry():
    # #180: a launchd process against a cmuxOnly socket gets this exact error.
    with (
        patch.object(WAKE_ROLE, "cmux", side_effect=RuntimeError(BROKEN_PIPE)) as cmux,
        patch.object(WAKE_ROLE.time, "sleep") as sleep,
    ):
        with pytest.raises(RuntimeError, match="socket_access_denied.*cmuxOnly"):
            WAKE_ROLE.preflight_socket()
    assert cmux.call_args_list == [call("ping")]
    sleep.assert_not_called()


def test_transient_socket_failure_recovers_within_bounded_retry():
    with (
        patch.object(
            WAKE_ROLE, "cmux", side_effect=[RuntimeError("Connection refused"), "PONG\n"]
        ) as cmux,
        patch.object(WAKE_ROLE.time, "sleep") as sleep,
    ):
        WAKE_ROLE.preflight_socket()
    assert cmux.call_count == 2
    sleep.assert_called_once()


def test_persistently_missing_socket_stops_after_bounded_attempts():
    with (
        patch.object(
            WAKE_ROLE, "cmux", side_effect=RuntimeError("No such file or directory")
        ) as cmux,
        patch.object(WAKE_ROLE.time, "sleep"),
    ):
        with pytest.raises(RuntimeError, match="socket_unavailable.*3 attempts"):
            WAKE_ROLE.preflight_socket()
    assert cmux.call_count == 3


def test_denied_socket_blocks_dispatch_before_any_surface_access(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "wake_role.py",
            "--role",
            "c",
            "--packet",
            "packet-180",
            "--work-url",
            "https://github.com/jayleekr/hypeproof-harness/issues/180",
            "--apply",
        ],
    )
    with (
        patch.object(WAKE_ROLE, "cmux", side_effect=RuntimeError(BROKEN_PIPE)),
        patch.object(WAKE_ROLE, "find_surface") as find_surface,
        patch.object(WAKE_ROLE, "send") as send,
    ):
        assert WAKE_ROLE.main() == 2

    result = json.loads(capsys.readouterr().err)
    assert result["status"] == "blocked"
    assert result["error"].startswith("socket_access_denied")
    find_surface.assert_not_called()
    send.assert_not_called()


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
