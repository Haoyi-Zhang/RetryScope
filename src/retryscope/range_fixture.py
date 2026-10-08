"""Small read-only HTTP fixture with byte-accurate Range replies for integration studies.

This is a reliability fixture, not a cloud emulator. Only a loopback listener is
created, response objects are at most 4096 bytes, and at most 16 arrivals are
allowed per operation. No caller-supplied remote endpoint is accepted.
"""
from __future__ import annotations
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from threading import Thread, Lock, Event
import hashlib
import re
import time

PAYLOAD = (b'0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_\n' * 2)[:96]

class RangeFixture:
    def __init__(self, scenario='success', *, payload=PAYLOAD, cut=7, s3=False, cap=16):
        if scenario not in {'success','transient','persistent','denied','truncated_once','corrupt_once','corrupt_always'}:
            raise ValueError('unsupported local scenario')
        if not 0 < len(payload) <= 4096 or not 0 <= cut <= len(payload) or not 1 <= cap <= 16:
            raise ValueError('unbounded fixture')
        self.scenario=scenario; self.payload=payload; self.cut=cut; self.s3=s3; self.cap=cap
        self.lock=Lock(); self.stop=Event(); self.count=0; self.active=0; self.events=[]; self.cap_exceeded=False
        owner=self
        class Handler(BaseHTTPRequestHandler):
            protocol_version='HTTP/1.1'
            def log_message(self,*args): pass
            def do_POST(self): self.send_error(405)
            do_PUT=do_DELETE=do_PATCH=do_POST
            def do_HEAD(self): self.do_GET()
            def do_GET(self):
                with owner.lock:
                    owner.count+=1; n=owner.count; owner.active+=1
                try:
                    if n>owner.cap:
                        owner.cap_exceeded=True;self.close_connection=True;return
                    status=503 if owner.scenario=='persistent' or (owner.scenario=='transient' and n==1) else 400 if owner.scenario=='denied' else 200
                    start=0;end=len(owner.payload)-1;range_header=self.headers.get('Range')
                    if range_header:
                        m=re.fullmatch(r'bytes=(\d+)-(\d*)',range_header)
                        if not m: self.send_error(416);return
                        start=int(m[1]);end=min(end,int(m[2])) if m[2] else end
                        if start>end: self.send_error(416);return
                    body=owner.payload[start:end+1]
                    if status>=400:
                        body=b'<Error><Code>InternalError</Code><Message>bounded local fixture</Message></Error>' if owner.s3 else b'local failure'
                    elif range_header:status=206
                    corrupt=owner.scenario=='corrupt_always' or owner.scenario=='corrupt_once' and n==1
                    if corrupt: body=bytes((b+1)%128 for b in body)
                    cut=owner.cut if owner.scenario=='truncated_once' and n==1 else len(body)
                    owner.add(kind='arrival',id=n,method=self.command,path=self.path,range=range_header,start=start,end=end,status=status,body_fault=cut<len(body),planned_bytes=len(body))
                    self.send_response(status)
                    self.send_header('Content-Length',str(len(body)))
                    self.send_header('Connection','close');self.send_header('Accept-Ranges','bytes')
                    self.send_header('Content-Type','application/octet-stream' if status<400 else 'application/xml')
                    self.send_header('ETag','"'+hashlib.sha256(owner.payload).hexdigest()+'"')
                    if status==206:self.send_header('Content-Range',f'bytes {start}-{end}/{len(owner.payload)}')
                    self.end_headers();owner.add(kind='headers_sent',id=n,status=status)
                    if self.command!='HEAD':
                        self.wfile.write(body[:cut]);self.wfile.flush()
                    owner.add(kind='body_end',id=n,bytes=0 if self.command=='HEAD' else min(cut,len(body)))
                    self.close_connection=True
                except (BrokenPipeError,ConnectionResetError,OSError) as e:
                    owner.add(kind='peer_closed',id=n,error=type(e).__name__)
                finally:
                    with owner.lock:owner.active-=1
                    owner.add(kind='handler_end',id=n)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.server.daemon_threads=True;self.server.block_on_close=False
        self.thread=Thread(target=self.server.serve_forever,kwargs={'poll_interval':.005},daemon=True)
    @property
    def url(self):return f'http://127.0.0.1:{self.server.server_port}'
    def add(self,**kw):
        with self.lock:self.events.append({'t':time.monotonic(),**kw})
    def __enter__(self):self.thread.start();return self
    def quiesce(self):
        end=time.monotonic()+1
        while time.monotonic()<end:
            with self.lock:
                if self.active==0:return True
            time.sleep(.002)
        return False
    def __exit__(self,*exc):
        self.quiesce();self.stop.set();self.server.shutdown();self.server.server_close();self.thread.join(1)
