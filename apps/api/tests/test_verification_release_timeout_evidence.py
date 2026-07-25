from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
from typing import Iterator

import pytest

from edu_grader_api.services import verification_release_timeout_evidence as evidence
from edu_grader_api.services.grader import GraderRequestTimeoutError, HttpGraderClient


class _GradeUpstreamHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(content_length)
        body = json.dumps(
            {
                "decision": "auto_accepted",
                "score": 1,
                "grader_version": "test-v1",
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *args: object) -> None:
        return


@contextmanager
def _grade_upstream() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _GradeUpstreamHandler)
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _allow_local_processor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(evidence.settings, "processor_allowed_hosts", "127.0.0.1")


def test_fault_proxy_produces_stable_read_timeout_and_single_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_local_processor(monkeypatch)
    monkeypatch.setattr(evidence.settings, "grader_request_timeout_seconds", 0.05)

    with evidence.FaultInjectingGraderProxy(
        "http://127.0.0.1:9",
        stall_seconds=0.15,
    ) as proxy:
        proxy.set_mode("stall")
        with pytest.raises(GraderRequestTimeoutError) as captured:
            HttpGraderClient(proxy.base_url).grade(
                "M1",
                {"expected": 4, "tolerance": 0},
                {"format": "text-v1", "text": "4"},
                policy_version="1",
            )

        assert captured.value.operation == "grade"
        assert proxy.call_counts() == {"stall": 1, "forward": 0}


def test_fault_proxy_forwards_real_http_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_local_processor(monkeypatch)
    monkeypatch.setattr(evidence.settings, "grader_request_timeout_seconds", 1.0)

    with _grade_upstream() as upstream:
        with evidence.FaultInjectingGraderProxy(
            upstream,
            stall_seconds=0.1,
        ) as proxy:
            proxy.set_mode("forward")
            result = HttpGraderClient(proxy.base_url).grade(
                "M1",
                {"expected": 4, "tolerance": 0},
                {"format": "text-v1", "text": "4"},
                policy_version="1",
            )

            assert result.decision == "auto_accepted"
            assert result.score == 1
            assert result.grader_version == "test-v1"
            assert proxy.call_counts() == {"stall": 0, "forward": 1}


def test_fault_proxy_rejects_non_positive_timeouts() -> None:
    with pytest.raises(ValueError, match="positive"):
        evidence.FaultInjectingGraderProxy(
            "http://127.0.0.1:9",
            stall_seconds=0,
        )


def test_call_buckets_are_stable() -> None:
    assert evidence._call_bucket(0) == "none"
    assert evidence._call_bucket(1) == "single"
    assert evidence._call_bucket(2) == "multiple"
