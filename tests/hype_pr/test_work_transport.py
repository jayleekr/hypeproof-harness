import importlib.util
import json
from pathlib import Path
import threading
import time

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("work_transport", ROOT / "scripts/hype-pr/work_transport.py")
work = importlib.util.module_from_spec(spec)
spec.loader.exec_module(work)


def test_live_request_reply_round_trip(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    monkeypatch.setenv("HYPE_PR_WORK_DIR", str(tmp_path))
    result = []
    thread = threading.Thread(target=lambda: result.append(work.exchange("read", {"path": "source"}, timeout=2)))
    thread.start()
    deadline = time.monotonic() + 1
    requests = []
    while not requests and time.monotonic() < deadline:
        requests = work.poll(tmp_path)["requests"]
        time.sleep(.01)
    assert requests
    request = requests[0]
    assert request["payload"] == {"path": "source"}
    (tmp_path / (request["id"] + ".reply")).write_text(json.dumps({
        "id": request["id"], "version": 1, "ok": True, "result": {"sha": "a" * 40}}))
    work.poll(tmp_path)
    thread.join(2)
    assert result == [{"sha": "a" * 40}]
    assert not list(tmp_path.glob("*.request"))


def test_missing_host_times_out_without_retry(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    monkeypatch.setenv("HYPE_PR_WORK_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="reconcile"):
        work.exchange("create", {}, timeout=.01)
    assert not list(tmp_path.glob("*.request"))


def test_shared_directory_is_rejected(tmp_path, monkeypatch):
    tmp_path.chmod(0o755)
    monkeypatch.setenv("HYPE_PR_WORK_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="0700"):
        work.exchange("read", {})


@pytest.mark.parametrize("wrong_id,ok", [(True, True), (False, False)])
def test_mismatched_or_failed_response_is_rejected(tmp_path, monkeypatch, wrong_id, ok):
    tmp_path.chmod(0o700)
    monkeypatch.setenv("HYPE_PR_WORK_DIR", str(tmp_path))
    class FixedUUID:
        hex = "a" * 32
    monkeypatch.setattr(work.uuid, "uuid4", FixedUUID)
    (tmp_path / ("a" * 32 + ".response")).write_text(json.dumps({
        "version": 1, "id": "b" * 32 if wrong_id else "a" * 32, "ok": ok, "result": {}}))
    with pytest.raises(ValueError):
        work.exchange("read", {}, timeout=1)


def test_host_adapter_contracts():
    import subprocess
    subprocess.run(["node", "--test", str(ROOT / "tests/hype_pr/work_host.test.js")], check=True)


def test_local_host_cache_never_reuses_mutable_refs(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    monkeypatch.setenv("HYPE_PR_WORK_DIR", str(tmp_path))
    source = "repos/x/y/contents/doc?ref=" + "a" * 40
    live = "repos/x/y/commits/main"
    value = {"encoding": "base64", "content": "eA=="}
    (tmp_path / "immutable-cache.json").write_text(json.dumps({source: value, live: {"sha": "old"}}))
    assert work.exchange("read", {"path": source}) == value
    with pytest.raises(ValueError, match="timed out"):
        work.exchange("read", {"path": live}, timeout=.01)
