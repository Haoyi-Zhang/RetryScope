"""Bounded loopback responder for causal-witness concurrency experiments."""
from __future__ import annotations

from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import re
from threading import Event, Lock, Thread
import time
from typing import Any

from .causal import parse_wire_headers

PAYLOAD = (b"RetryScope-causal-witness-payload-" * 8)[:192]
_RANGE = re.compile(r"bytes=(\d+)-(\d*)")


class CausalResponder:
    """Read-only fixture; accepts no remote endpoint and caps every operation."""

    def __init__(self, *, per_operation_cap: int = 16, truncate_at: int = 37) -> None:
        if not 1 <= per_operation_cap <= 16:
            raise ValueError("per_operation_cap must be in 1..16")
        if not 1 <= truncate_at < len(PAYLOAD):
            raise ValueError("truncate_at must be within the payload")
        self.per_operation_cap = per_operation_cap
        self.truncate_at = truncate_at
        self.lock = Lock()
        self.stop = Event()
        self.events: list[dict[str, Any]] = []
        self.global_count = 0
        self.active = 0
        self.counts: dict[tuple[str, str], int] = defaultdict(int)
        self.operation_counts: dict[str, int] = defaultdict(int)
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args: Any) -> None:
                return

            def do_POST(self) -> None:
                self.send_error(405)

            do_PUT = do_DELETE = do_PATCH = do_POST

            def do_HEAD(self) -> None:
                self._serve(send_body=False)

            def do_GET(self) -> None:
                self._serve(send_body=True)

            def _serve(self, *, send_body: bool) -> None:
                parsed = parse_wire_headers(self.headers)
                op = parsed.get("operation_id")
                attempt = parsed.get("attempt_id")
                with owner.lock:
                    owner.global_count += 1
                    global_index = owner.global_count
                    owner.active += 1
                    if isinstance(op, str):
                        owner.operation_counts[op] += 1
                        operation_index = owner.operation_counts[op]
                    else:
                        operation_index = 0
                    key = (str(op), self.path.split("?", 1)[0])
                    owner.counts[key] += 1
                    path_index = owner.counts[key]
                try:
                    if not parsed["valid"] or operation_index > owner.per_operation_cap:
                        owner.add(
                            kind="arrival",
                            global_index=global_index,
                            operation_index=operation_index,
                            operation_id=op,
                            attempt_id=attempt,
                            witness_valid=False,
                            witness_errors=parsed["errors"] or ["operation cap exceeded"],
                            path=self.path,
                            method=self.command,
                        )
                        self.send_response(400)
                        body = b"invalid witness"
                        self.send_header("Content-Length", str(len(body)))
                        self.send_header("Connection", "close")
                        self.end_headers()
                        if send_body:
                            self.wfile.write(body)
                        return

                    route = self.path.split("?", 1)[0]
                    status = 200
                    body = PAYLOAD
                    truncate = False
                    if route == "/retry":
                        status = 503 if path_index == 1 else 200
                    elif route == "/nested":
                        status = 503 if path_index <= 3 else 200
                    elif route == "/constituent/meta":
                        body = b"metadata"
                    elif route == "/constituent/a":
                        body = PAYLOAD[:64]
                    elif route == "/constituent/b":
                        status = 503 if path_index == 1 else 200
                        body = PAYLOAD[64:]
                    elif route == "/recovery":
                        range_header = self.headers.get("Range")
                        if range_header is None and path_index == 1:
                            truncate = True
                        elif range_header is not None:
                            match = _RANGE.fullmatch(range_header)
                            if not match:
                                self.send_error(416)
                                return
                            start = int(match.group(1))
                            end = len(PAYLOAD) - 1 if not match.group(2) else min(len(PAYLOAD) - 1, int(match.group(2)))
                            if start > end:
                                self.send_error(416)
                                return
                            body = PAYLOAD[start : end + 1]
                            status = 206
                    elif route == "/success":
                        pass
                    else:
                        status = 404
                        body = b"not found"

                    owner.add(
                        kind="arrival",
                        global_index=global_index,
                        operation_index=operation_index,
                        operation_id=op,
                        attempt_id=attempt,
                        ordinal=parsed.get("ordinal"),
                        witness_valid=True,
                        traceparent=parsed.get("traceparent"),
                        path=self.path,
                        method=self.command,
                        status=status,
                    )
                    self.send_response(status)
                    declared = len(body)
                    self.send_header("Content-Length", str(declared))
                    self.send_header("Connection", "close")
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Accept-Ranges", "bytes")
                    if status == 206:
                        start = len(PAYLOAD) - len(body)
                        self.send_header("Content-Range", f"bytes {start}-{len(PAYLOAD)-1}/{len(PAYLOAD)}")
                    self.end_headers()
                    if send_body:
                        if truncate:
                            self.wfile.write(body[: owner.truncate_at])
                            self.wfile.flush()
                            self.close_connection = True
                            return
                        self.wfile.write(body)
                        self.wfile.flush()
                    self.close_connection = True
                except (BrokenPipeError, ConnectionResetError, OSError) as exc:
                    owner.add(
                        kind="peer_closed",
                        global_index=global_index,
                        operation_id=op,
                        attempt_id=attempt,
                        error=type(exc).__name__,
                    )
                finally:
                    with owner.lock:
                        owner.active -= 1

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.server.block_on_close = False
        self.thread = Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.005}, daemon=True)

    def add(self, **event: Any) -> None:
        with self.lock:
            self.events.append({"t": time.monotonic(), "t_ns": time.monotonic_ns(), **event})

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def __enter__(self) -> "CausalResponder":
        self.thread.start()
        return self

    def quiesce(self, timeout: float = 2.0) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with self.lock:
                if self.active == 0:
                    return True
            time.sleep(0.001)
        return False

    def __exit__(self, *_exc: Any) -> None:
        self.quiesce()
        self.stop.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
