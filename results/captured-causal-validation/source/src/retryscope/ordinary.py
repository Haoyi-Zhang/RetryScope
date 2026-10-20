"""Ordinary opt-in baselines, not a novel retry algorithm or deadline enforcer.

The length check intentionally supports only fully buffered identity-encoded
responses. It is not suitable for compressed, streaming or unbounded bodies.
"""
from __future__ import annotations
from typing import Any

def checked_identity_body(response: Any, incomplete_error: type[Exception]) -> bytes:
    response.raise_for_status()
    if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
        raise ValueError('length baseline requires identity encoding')
    body = response.content
    length = response.headers.get('Content-Length')
    if length is None or not length.isdigit():
        raise ValueError('length baseline requires a valid Content-Length')
    if len(body) != int(length):
        raise incomplete_error('incomplete identity-encoded body')
    return body

def total_attempt_config(total: int = 2):
    """An SDK-call cap, NOT a cap for downstream streaming-body reopens."""
    if isinstance(total, bool) or not isinstance(total, int) or not 1 <= total <= 16:
        raise ValueError('total must be an integer from 1 to 16')
    from botocore.config import Config
    return Config(retries={'mode': 'standard', 'total_max_attempts': total})
