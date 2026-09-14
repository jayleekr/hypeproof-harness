from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "skills/hype-coordinate/scripts/watch_delivery.py"
SPEC = importlib.util.spec_from_file_location("hype_coordinate_watch_delivery", MODULE_PATH)
assert SPEC and SPEC.loader
WATCH = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = WATCH
SPEC.loader.exec_module(WATCH)


def record(*, changed: bool = False) -> dict:
    payload = {
        "repo": "jayleekr/hypeproof-studio",
        "number": 1043,
        "url": "https://github.com/jayleekr/hypeproof-studio/pull/1043",
    }
    if changed:
        payload = {"before": None, "after": payload}
    return {"token": "token-172", "payload": payload}


def test_record_url_handles_existing_and_changed_payloads() -> None:
    assert WATCH.record_url(record()) == "https://github.com/jayleekr/hypeproof-studio/pull/1043"
    assert WATCH.record_url(record(changed=True)) == "https://github.com/jayleekr/hypeproof-studio/pull/1043"


def test_unchanged_scan_never_wakes_a(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "argv", ["watch_delivery.py", "--state-file", str(tmp_path / "state.json"), "--apply"])
    with patch.object(WATCH, "run_json", return_value=(0, {"changed": False, "delta": {"backlog": []}}, "")) as run:
        assert WATCH.main() == 0
    assert run.call_count == 1
    assert json.loads(capsys.readouterr().out)["status"] == "unchanged"


def test_changed_scan_wakes_a_once_and_keeps_token_unaccepted(monkeypatch, capsys, tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    monkeypatch.setattr(sys, "argv", ["watch_delivery.py", "--state-file", str(state), "--apply"])
    delta = {"changed": True, "delta": {"backlog": [record(changed=True)]}}
    wake = {"status": "submitted_pending_ack", "dispatch_attempt": "WAKE_ATTEMPT_A_1", "accepted": False}
    with patch.object(WATCH, "run_json", side_effect=[(0, delta, ""), (0, wake, "")]) as run:
        assert WATCH.main() == 0

    assert run.call_count == 2
    wake_args = run.call_args_list[1].args[0]
    assert wake_args[wake_args.index("--role") + 1] == "a"
    assert wake_args[wake_args.index("--state-file") + 1] == str(state.resolve())
    result = json.loads(capsys.readouterr().out)
    assert result["dispatched"] is True
    assert result["accepted"] is False


def loop_argv(monkeypatch, state: Path, *extra: str) -> None:
    monkeypatch.setattr(
        sys, "argv",
        ["watch_delivery.py", "--state-file", str(state), "--apply", "--loop", "--interval", "60", *extra],
    )


def test_loop_emits_one_line_per_tick_and_waits_between(monkeypatch, capsys, tmp_path: Path) -> None:
    loop_argv(monkeypatch, tmp_path / "state.json", "--max-ticks", "2")
    unchanged = (0, {"changed": False, "delta": {"backlog": []}}, "")
    with (
        patch.object(WATCH.os, "getppid", return_value=4242),
        patch.object(WATCH, "run_json", return_value=unchanged) as run,
        patch.object(WATCH.time, "sleep") as sleep,
    ):
        assert WATCH.main() == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [line["status"] for line in lines] == ["unchanged", "unchanged"]
    assert run.call_count == 2
    assert sleep.call_count == 60


def test_loop_stops_when_socket_access_is_denied(monkeypatch, capsys, tmp_path: Path) -> None:
    # #180: a rejected cmux socket cannot recover by retrying; the loop must end.
    loop_argv(monkeypatch, tmp_path / "state.json")
    delta = {"changed": True, "delta": {"backlog": [record()]}}
    denied = '{"status":"blocked","error":"socket_access_denied: cmux rejected this process"}'
    with (
        patch.object(WATCH.os, "getppid", return_value=4242),
        patch.object(WATCH, "run_json", side_effect=[(0, delta, ""), (2, {}, denied)]) as run,
        patch.object(WATCH.time, "sleep") as sleep,
    ):
        assert WATCH.main() == WATCH.EXIT_SOCKET_DENIED
    assert run.call_count == 2
    sleep.assert_not_called()
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"


def test_loop_adopted_by_launchd_refuses_before_scanning(monkeypatch, capsys, tmp_path: Path) -> None:
    loop_argv(monkeypatch, tmp_path / "state.json")
    with (
        patch.object(WATCH.os, "getppid", return_value=1),
        patch.object(WATCH, "run_json") as run,
    ):
        assert WATCH.main() == WATCH.EXIT_SOCKET_DENIED
    run.assert_not_called()
    assert "adopted by launchd" in json.loads(capsys.readouterr().out)["error"]


def test_second_loop_instance_exits_without_scanning(monkeypatch, capsys, tmp_path: Path) -> None:
    import fcntl

    state = tmp_path / "state.json"
    loop_argv(monkeypatch, state)
    holder = (tmp_path / "state.json.loop.lock").open("a+")
    fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with (
            patch.object(WATCH.os, "getppid", return_value=4242),
            patch.object(WATCH, "run_json") as run,
        ):
            assert WATCH.main() == 0
    finally:
        holder.close()
    run.assert_not_called()
    assert json.loads(capsys.readouterr().out)["status"] == "already_running"


def test_loop_rejects_out_of_range_interval(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(
        sys, "argv",
        ["watch_delivery.py", "--state-file", str(tmp_path / "s.json"), "--loop", "--interval", "5"],
    )
    with patch.object(WATCH, "run_json") as run:
        assert WATCH.main() == 2
    run.assert_not_called()


def test_failed_wake_keeps_pending_work_blocked(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "argv", ["watch_delivery.py", "--state-file", str(tmp_path / "state.json"), "--apply"])
    delta = {"changed": True, "delta": {"backlog": [record()]}}
    with patch.object(WATCH, "run_json", side_effect=[(0, delta, ""), (2, {}, "target role is running")]):
        assert WATCH.main() == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "blocked"
    assert result["dispatched"] is False
