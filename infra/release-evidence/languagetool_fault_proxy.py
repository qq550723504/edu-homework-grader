"""Container-local LanguageTool response-stall proxy for release evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from threading import Lock
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


Mode = str


@dataclass(slots=True)
class FaultState:
    mode: Mode = "forward"
    counts: dict[str, int] = field(default_factory=lambda: {"stall": 0, "forward": 0})
    lock: Lock = field(default_factory=Lock)

    def set_mode(self, mode: Mode) -> None:
        if mode not in {"stall", "forward"}:
            raise ValueError("unsupported fault mode")
        with self.lock:
            self.mode = mode

    def reset(self) -> None:
        with self.lock:
            self.counts = {"stall": 0, "forward": 0}

    def record(self) -> Mode:
        with self.lock:
            mode = self.mode
            self.counts[mode] += 1
            return mode

    def snapshot(self) -> dict[str, int]:
        with self.lock:
            return dict(self.counts)


class FaultProxyServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        *,
        upstream_base: str,
        stall_seconds: float,
        forward_timeout_seconds: float,
    ) -> None:
        super().__init__(server_address, FaultProxyHandler)
        self.upstream_base = upstream_base.rstrip("/")
        self.stall_seconds = stall_seconds
        self.forward_timeout_seconds = forward_timeout_seconds
        self.state = FaultState()


class FaultProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/__fault/health":
            self._json_response(200, {"status": "ok"})
            return
        if self.path == "/__fault/counts":
            self._json_response(200, self.server.state.snapshot())  # type: ignore[attr-defined]
            return
        self._empty_response(404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/__fault/reset":
            self.server.state.reset()  # type: ignore[attr-defined]
            self._json_response(200, self.server.state.snapshot())  # type: ignore[attr-defined]
            return
        if self.path == "/__fault/mode":
            payload = self._json_body()
            mode = payload.get("mode") if isinstance(payload, dict) else None
            try:
                self.server.state.set_mode(mode)  # type: ignore[attr-defined]
            except ValueError:
                self._empty_response(400)
                return
            self._json_response(200, {"mode": mode})
            return
        self._proxy_request()

    def _proxy_request(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length)
        mode = self.server.state.record()  # type: ignore[attr-defined]
        self.close_connection = True
        if mode == "stall":
            time.sleep(self.server.stall_seconds)  # type: ignore[attr-defined]
            return

        request = Request(
            f"{self.server.upstream_base}{self.path}",  # type: ignore[attr-defined]
            data=body,
            headers={
                "Content-Type": self.headers.get(
                    "Content-Type", "application/x-www-form-urlencoded"
                )
            },
            method="POST",
        )
        try:
            with urlopen(  # noqa: S310
                request,
                timeout=self.server.forward_timeout_seconds,  # type: ignore[attr-defined]
            ) as response:
                response_body = response.read()
                self._raw_response(
                    response.status,
                    response_body,
                    response.headers.get("Content-Type"),
                )
        except HTTPError as error:
            self._raw_response(
                error.code,
                error.read(),
                error.headers.get("Content-Type"),
            )
        except (OSError, TimeoutError, URLError):
            self._empty_response(502)

    def _json_body(self) -> object:
        length = int(self.headers.get("Content-Length", "0"))
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None

    def _json_response(self, status: int, payload: object) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self._raw_response(status, body, "application/json")

    def _empty_response(self, status: int) -> None:
        self._raw_response(status, b"", None)

    def _raw_response(
        self,
        status: int,
        body: bytes,
        content_type: str | None,
    ) -> None:
        self.send_response(status)
        if content_type:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        if body:
            try:
                self.wfile.write(body)
            except BrokenPipeError:
                return

    def log_message(self, _format: str, *args: object) -> None:
        return


def create_server(
    host: str,
    port: int,
    *,
    upstream_base: str,
    stall_seconds: float,
    forward_timeout_seconds: float,
) -> FaultProxyServer:
    if stall_seconds <= 0 or forward_timeout_seconds <= 0:
        raise ValueError("fault proxy timeouts must be positive")
    return FaultProxyServer(
        (host, port),
        upstream_base=upstream_base,
        stall_seconds=stall_seconds,
        forward_timeout_seconds=forward_timeout_seconds,
    )


def main() -> None:
    server = create_server(
        "0.0.0.0",
        int(os.environ.get("LANGUAGETOOL_FAULT_PROXY_PORT", "8020")),
        upstream_base=os.environ.get(
            "LANGUAGETOOL_FAULT_PROXY_UPSTREAM",
            "http://languagetool:8010",
        ),
        stall_seconds=float(
            os.environ.get("LANGUAGETOOL_FAULT_PROXY_STALL_SECONDS", "6")
        ),
        forward_timeout_seconds=float(
            os.environ.get("LANGUAGETOOL_FAULT_PROXY_FORWARD_TIMEOUT_SECONDS", "15")
        ),
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
