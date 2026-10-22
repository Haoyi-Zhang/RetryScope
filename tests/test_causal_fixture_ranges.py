"""Ordinary single-range responses from the bounded owned loopback fixture."""
from http.client import HTTPConnection
from urllib.parse import urlsplit

import pytest

from retryscope.causal_fixture import CausalResponder, PAYLOAD


@pytest.mark.parametrize("method,range_value,start,end", [
    ("GET", "bytes=7-15", 7, 15),
    ("GET", "bytes=0-0", 0, 0),
    ("GET", "bytes=32-", 32, len(PAYLOAD) - 1),
    ("GET", "bytes=180-999", 180, len(PAYLOAD) - 1),
    ("HEAD", "bytes=7-15", 7, 15),
])
def test_range_header_matches_selected_payload(method, range_value, start, end):
    op, attempt = "1" * 32, "2" * 16
    headers = {
        "x-retryscope-operation": op,
        "x-retryscope-attempt": attempt,
        "x-retryscope-ordinal": "1",
        "traceparent": f"00-{op}-{attempt}-01",
        "Range": range_value,
    }
    with CausalResponder() as fixture:
        address = urlsplit(fixture.url)
        connection = HTTPConnection(address.hostname, address.port, timeout=2)
        try:
            connection.request(method, "/recovery", headers=headers)
            response = connection.getresponse()
            body = response.read()
            assert response.status == 206
            assert response.getheader("Content-Length") == str(end - start + 1)
            assert response.getheader("Content-Range") == f"bytes {start}-{end}/{len(PAYLOAD)}"
            assert body == (b"" if method == "HEAD" else PAYLOAD[start:end + 1])
        finally:
            connection.close()
        assert fixture.quiesce()
