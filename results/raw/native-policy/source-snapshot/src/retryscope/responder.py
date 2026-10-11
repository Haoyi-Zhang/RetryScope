"""Bounded loopback-only read responder. No production target is accepted."""
from __future__ import annotations
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread, Lock, Event
import time
import socket

@dataclass(frozen=True)
class Reply:
    status: int = 200
    body: bytes = b"0123456789"
    header_delay: float = 0.0
    chunk_delay: float = 0.0
    truncate: bool = False
    retry_after: str | None = None

    def __post_init__(self):
        if len(self.body) > 4096 or not 0 <= self.header_delay <= 0.5 or not 0 <= self.chunk_delay <= 0.1:
            raise ValueError("unsafe responder parameters")
        if self.retry_after is not None and self.retry_after not in ("0", "1"):
            raise ValueError("retry delay must be bounded")

class Responder:
    def __init__(self, replies: list[Reply], cap: int = 16, s3: bool = False):
        if not replies or not 1 <= cap <= 16:
            raise ValueError("invalid script or request cap")
        self.replies = replies
        self.cap = cap
        self.s3 = s3
        self.events: list[dict] = []
        self.lock = Lock()
        self.stop = Event()
        self.count = 0
        self.active = 0
        self.cap_exceeded = False
        owner = self
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def log_message(self, *args):
                pass
            def do_POST(self):
                self.send_error(405)
            do_PUT = do_DELETE = do_PATCH = do_POST
            def do_HEAD(self):
                self.do_GET()
            def do_GET(self):
                with owner.lock:
                    owner.count += 1
                    n = owner.count
                    owner.active += 1
                try:
                    if n > owner.cap:
                        owner.cap_exceeded = True
                        self.close_connection = True
                        return
                    reply = owner.replies[min(n - 1, len(owner.replies) - 1)]
                    body = reply.body
                    status = reply.status
                    if owner.s3 and status >= 400:
                        code = "InternalError" if status == 503 else "InvalidRequest"
                        body = f"<Error><Code>{code}</Code><Message>local fixture</Message></Error>".encode()
                    ranged = owner.s3 and self.headers.get("Range") is not None and status == 200
                    if ranged:
                        status = 206
                    owner.add(kind="arrival", index=n, status=reply.status,
                              path=self.path, method=self.command, range=self.headers.get("Range"),
                              body_fault=reply.truncate, header_delay=reply.header_delay)
                    if owner.stop.wait(reply.header_delay):
                        return
                    self.send_response(status)
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Connection", "close")
                    self.send_header("Content-Type", "application/octet-stream" if status < 400 else "application/xml" if owner.s3 else "application/json")
                    if ranged:
                        self.send_header("Content-Range", f"bytes 0-{len(body)-1}/{len(body)}")
                    if reply.retry_after is not None:
                        self.send_header("Retry-After", reply.retry_after)
                    self.end_headers()
                    owner.add(kind="headers_sent", index=n, status=status)
                    if self.command == "HEAD":
                        return
                    if reply.truncate:
                        self.wfile.write(body[:2]); self.wfile.flush()
                    elif reply.chunk_delay:
                        for byte in body:
                            if owner.stop.wait(reply.chunk_delay):
                                return
                            self.wfile.write(bytes([byte])); self.wfile.flush()
                            owner.add(kind="body_chunk", index=n, bytes=1)
                    else:
                        self.wfile.write(body); self.wfile.flush()
                    owner.add(kind="body_end", index=n, bytes=2 if reply.truncate else len(body), truncated=reply.truncate)
                    self.close_connection = True
                except (BrokenPipeError, ConnectionResetError, OSError) as exc:
                    owner.add(kind="peer_closed", index=n, exception=type(exc).__name__)
                finally:
                    with owner.lock:
                        owner.active -= 1
                    owner.add(kind="handler_end", index=n)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.server.block_on_close = False
        self.thread = Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.005}, daemon=True)

    def add(self, **event):
        with self.lock:
            self.events.append({"t": time.monotonic(), **event})

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def __enter__(self):
        self.thread.start()
        return self

    def quiesce(self, timeout: float = 1.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with self.lock:
                if not self.active:
                    return True
            time.sleep(0.002)
        return False

    def __exit__(self, *args):
        self.quiesce()
        self.stop.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)
