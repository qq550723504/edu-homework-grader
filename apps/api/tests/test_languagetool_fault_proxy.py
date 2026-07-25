from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import sys
from threading import Thread
import time
from types import ModuleType
from typing import Iterator

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "infra" / "release-evidence" / "languagetool_fault_proxy.py"


def _load_proxy_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "release_evidence_languagetool_fault_proxy",
        SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("fault proxy module could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _LanguageToolHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        body = json.dumps({"matches": []}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *args: object) -> None:
        return


@contextmanager
def _upstream() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _LanguageToolHandler)
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


@contextmanager
def _proxy(upstream: str) -> Iterator[str]:
    module = _load_proxy_module()
    server = module.create_server(
        "127.0.0.1",
        0,
        upstream_base=upstream,
        stall_seconds=0.15,
        forward_timeout_seconds=1.0,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_proxy_control_forwards_and_stalls_without_payload_evidence() -> None:
    with _upstream() as upstream, _proxy(upstream) as proxy:
        assert httpx.get(f"{proxy}/__fault/health").json() == {"status": "ok"}
        httpx.post(f"{proxy}/__fault/reset").raise_for_status()
        httpx.post(
            f"{proxy}/__fault/mode",
            json={"mode": "forward"},
        ).raise_for_status()
        forwarded = httpx.post(
            f"{proxy}/v2/check",
            data={"text": "synthetic", "language": "en-US"},
        )
        assert forwarded.status_code == 200
        assert forwarded.json() == {"matches": []}
        assert httpx.get(f"{proxy}/__fault/counts").json() == {
            "forward": 1,
            "stall": 0,
        }

        httpx.post(f"{proxy}/__fault/reset").raise_for_status()
        httpx.post(
            f"{proxy}/__fault/mode",
            json={"mode": "stall"},
        ).raise_for_status()
        with pytest.raises(httpx.ReadTimeout):
            httpx.post(
                f"{proxy}/v2/check",
                data={"text": "synthetic", "language": "en-US"},
                timeout=0.05,
            )
        time.sleep(0.18)
        assert httpx.get(f"{proxy}/__fault/counts").json() == {
            "forward": 0,
            "stall": 1,
        }


def test_proxy_rejects_unknown_mode() -> None:
    with _upstream() as upstream, _proxy(upstream) as proxy:
        response = httpx.post(
            f"{proxy}/__fault/mode",
            json={"mode": "unknown"},
        )
        assert response.status_code == 400
