from __future__ import annotations

import http.client
import importlib.util
import json
import socket
import threading
from contextlib import contextmanager
from functools import partial
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Iterator

import pytest


ROOT = Path(__file__).resolve().parents[2]
VIEWER = ROOT / "skills" / "skill-creator" / "eval-viewer" / "generate_review.py"

spec = importlib.util.spec_from_file_location("eval_viewer_generate_review", VIEWER)
assert spec and spec.loader
eval_viewer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(eval_viewer)


@contextmanager
def running_viewer(tmp_path: Path, csrf_token: str = "test-token") -> Iterator[tuple[int, Path]]:
    feedback_path = tmp_path / "feedback.json"
    handler = partial(
        eval_viewer.ReviewHandler,
        tmp_path,
        "skill",
        feedback_path,
        {},
        None,
        csrf_token,
    )
    server, port, _ = eval_viewer._bind_server(0, handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield port, feedback_path
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def post_feedback(port: int, body: bytes, headers: dict[str, str]) -> tuple[int, bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("POST", "/api/feedback", body=body, headers=headers)
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


def raw_post_with_declared_length(port: int, length: int, headers: dict[str, str]) -> str:
    lines = [
        "POST /api/feedback HTTP/1.1",
        f"Host: localhost:{port}",
        f"Content-Length: {length}",
        "Connection: close",
    ]
    lines.extend(f"{name}: {value}" for name, value in headers.items())
    request = "\r\n".join(lines).encode("ascii") + b"\r\n\r\n"
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(request)
        return sock.recv(1024).decode("utf-8", errors="replace")


def test_feedback_post_saves_valid_payload(tmp_path: Path) -> None:
    with running_viewer(tmp_path) as (port, feedback_path):
        payload = {
            "reviews": [{"run_id": "run-1", "feedback": "looks good", "timestamp": "2026-06-09T00:00:00Z"}],
            "status": "complete",
        }
        status, _ = post_feedback(
            port,
            json.dumps(payload).encode("utf-8"),
            {
                "Content-Type": "application/json",
                "Origin": f"http://localhost:{port}",
                eval_viewer.CSRF_HEADER: "test-token",
            },
        )

        assert status == 200
        assert json.loads(feedback_path.read_text()) == payload


def test_feedback_post_requires_csrf_token(tmp_path: Path) -> None:
    with running_viewer(tmp_path) as (port, feedback_path):
        status, _ = post_feedback(
            port,
            b'{"reviews":[],"status":"in_progress"}',
            {
                "Content-Type": "application/json",
                "Origin": f"http://localhost:{port}",
            },
        )

        assert status == 403
        assert not feedback_path.exists()


def test_feedback_post_rejects_non_localhost_origin(tmp_path: Path) -> None:
    with running_viewer(tmp_path) as (port, feedback_path):
        status, _ = post_feedback(
            port,
            b'{"reviews":[],"status":"in_progress"}',
            {
                "Content-Type": "application/json",
                "Origin": f"http://example.com:{port}",
                eval_viewer.CSRF_HEADER: "test-token",
            },
        )

        assert status == 403
        assert not feedback_path.exists()


def test_feedback_post_rejects_wrong_content_type(tmp_path: Path) -> None:
    with running_viewer(tmp_path) as (port, feedback_path):
        status, _ = post_feedback(
            port,
            b'{"reviews":[],"status":"in_progress"}',
            {
                "Content-Type": "text/plain",
                "Origin": f"http://localhost:{port}",
                eval_viewer.CSRF_HEADER: "test-token",
            },
        )

        assert status == 415
        assert not feedback_path.exists()


def test_feedback_post_rejects_large_payload(tmp_path: Path) -> None:
    with running_viewer(tmp_path) as (port, feedback_path):
        response = raw_post_with_declared_length(
            port,
            eval_viewer.MAX_FEEDBACK_BYTES + 1,
            {
                "Content-Type": "application/json",
                "Origin": f"http://localhost:{port}",
                eval_viewer.CSRF_HEADER: "test-token",
            },
        )

        assert " 413 " in response
        assert not feedback_path.exists()


def test_feedback_payload_validation_requires_review_shape() -> None:
    valid = {
        "reviews": [{"run_id": "run-1", "feedback": "", "timestamp": "2026-06-09T00:00:00Z"}],
        "status": "in_progress",
    }
    assert eval_viewer._validate_feedback_payload(valid) == valid

    with pytest.raises(ValueError, match="reviews"):
        eval_viewer._validate_feedback_payload({"reviews": "not-a-list"})
    with pytest.raises(ValueError, match="run_id"):
        eval_viewer._validate_feedback_payload({"reviews": [{"feedback": "missing run"}]})
    with pytest.raises(ValueError, match="status"):
        eval_viewer._validate_feedback_payload({"reviews": [], "status": "unexpected"})


def test_json_content_type_allows_charset_only() -> None:
    assert eval_viewer._is_json_content_type("application/json")
    assert eval_viewer._is_json_content_type("application/json; charset=utf-8")
    assert not eval_viewer._is_json_content_type("text/plain")
    assert not eval_viewer._is_json_content_type(None)


def test_origin_check_is_limited_to_local_viewer_origin() -> None:
    assert eval_viewer._is_allowed_origin(None, 3117)
    assert eval_viewer._is_allowed_origin("http://localhost:3117", 3117)
    assert eval_viewer._is_allowed_origin("http://127.0.0.1:3117", 3117)
    assert not eval_viewer._is_allowed_origin("https://localhost:3117", 3117)
    assert not eval_viewer._is_allowed_origin("http://localhost:3118", 3117)
    assert not eval_viewer._is_allowed_origin("http://example.com:3117", 3117)


def test_bind_server_falls_back_without_killing_busy_port() -> None:
    class QuietHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        busy_port = sock.getsockname()[1]

        server, actual_port, used_fallback = eval_viewer._bind_server(busy_port, QuietHandler)
        try:
            assert used_fallback
            assert actual_port != busy_port
            assert sock.fileno() >= 0
        finally:
            server.server_close()
