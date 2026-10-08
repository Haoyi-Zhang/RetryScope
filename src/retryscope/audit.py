"""Evidence-aware finite-trace audit, version 2.

Unknown data never establishes conformance. A witnessed violation is retained even
when another dimension or the rest of the trace is unknown. This is an offline
observer, not a deadline enforcer. The archived checker.py is retained unchanged
solely so the first study's published raw labels remain reproducible.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any, Mapping
import math


def finite_nonnegative(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x >= 0


@dataclass(frozen=True)
class AuditIntent:
    max_wire_attempts: int | None = None
    retryable_statuses: tuple[int, ...] | None = None
    allow_body_recovery: bool = False
    allow_transport_retry: bool = False
    allow_integrity_retry: bool = False
    expected_payload: str | None = None
    required_outcome: str | None = None
    budget_s: float | None = None
    tolerance_s: float = 0.020
    time_scope: str = 'operation'
    boundary: str = 'body'
    provenance: str = 'explicit local probe, not an upstream defect oracle'

    def __post_init__(self) -> None:
        if self.max_wire_attempts is not None and (isinstance(self.max_wire_attempts, bool) or not isinstance(self.max_wire_attempts, int) or not 1 <= self.max_wire_attempts <= 16):
            raise ValueError('max_wire_attempts must be an integer in 1..16')
        if self.retryable_statuses is not None and any(isinstance(s, bool) or not isinstance(s, int) or not 100 <= s <= 599 for s in self.retryable_statuses):
            raise ValueError('invalid HTTP status')
        if self.required_outcome not in (None, 'success', 'error'):
            raise ValueError('invalid outcome contract')
        if self.budget_s is not None and (not finite_nonnegative(self.budget_s) or self.budget_s == 0):
            raise ValueError('budget must be finite and positive')
        if not finite_nonnegative(self.tolerance_s):
            raise ValueError('invalid tolerance')
        if self.time_scope not in ('operation', 'admission') or self.boundary not in ('headers', 'body', 'cleanup'):
            raise ValueError('unsupported time boundary')

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def combine(states: list[str]) -> str:
    """Conjunction in a three-valued evidence domain; violation has priority."""
    if 'mismatch' in states:
        return 'mismatch'
    if not states or 'unknown' in states:
        return 'unknown'
    return 'pass'


def audit(record: Mapping[str, Any], intent: AuditIntent) -> dict[str, Any]:
    dimensions: dict[str, dict[str, Any]] = {}
    def put(name: str, verdict: str, reason: str, **evidence: Any) -> None:
        dimensions[name] = {'verdict': verdict, 'reason': reason, **evidence}

    arrivals = record.get('arrivals')
    valid_arrivals = isinstance(arrivals, list) and all(isinstance(a, dict) and isinstance(a.get('id'), int) and not isinstance(a.get('id'), bool) and a['id'] > 0 for a in arrivals)
    if valid_arrivals:
        valid_arrivals = len({a['id'] for a in arrivals}) == len(arrivals)
    if intent.max_wire_attempts is not None:
        observed = record.get('wire_attempts_observed', len(arrivals) if valid_arrivals else None)
        count_valid = type(observed) is int and observed >= 0
        if count_valid and observed > intent.max_wire_attempts:
            put('attempts', 'mismatch', 'observed prefix already exceeds cap', observed=observed, limit=intent.max_wire_attempts)
        elif not count_valid:
            put('attempts', 'unknown', 'missing or malformed request inventory')
        elif record.get('arrival_stream_complete') is not True:
            put('attempts', 'unknown', 'request inventory is only a prefix', observed=observed)
        else:
            put('attempts', 'pass', 'complete inventory satisfies cap', observed=observed)

    if intent.required_outcome is not None:
        outcome = record.get('outcome')
        if outcome not in ('success', 'error'):
            put('outcome', 'unknown', 'missing terminal outcome')
        else:
            put('outcome', 'pass' if outcome == intent.required_outcome else 'mismatch', 'observed terminal outcome', observed=outcome)

    if intent.expected_payload is not None:
        outcome = record.get('outcome')
        if outcome == 'error':
            put('payload', 'pass', 'success-conditional obligation is vacuous on error')
        elif outcome != 'success' or 'payload' not in record or not isinstance(record['payload'], str):
            put('payload', 'unknown', 'successful complete payload was not observed')
        elif record.get('payload_complete') is not True:
            put('payload', 'unknown', 'payload has no complete-body witness')
        else:
            put('payload', 'pass' if record['payload'] == intent.expected_payload else 'mismatch', 'complete returned payload compared', observed=record['payload'])

    if intent.retryable_statuses is not None:
        states: list[str] = []
        reasons: list[dict[str, Any]] = []
        if not valid_arrivals:
            states.append('unknown')
        else:
            ids = {a['id'] for a in arrivals}
            for a in arrivals:
                role = a.get('role')
                if role in ('initial', 'constituent') and a.get('attribution_witness'):
                    states.append('pass')
                elif role in ('retry', 'recovery') and a.get('attribution_witness') and a.get('retry_of') in ids and a['retry_of'] < a['id']:
                    cause = a.get('cause', {})
                    kind = cause.get('kind')
                    if kind == 'status' and type(cause.get('received_status')) is int and 100 <= cause['received_status'] <= 599:
                        states.append('pass' if cause['received_status'] in intent.retryable_statuses else 'mismatch')
                    elif kind == 'body_error':
                        states.append('pass' if intent.allow_body_recovery else 'mismatch')
                    elif kind == 'transport_error':
                        states.append('pass' if intent.allow_transport_retry else 'mismatch')
                    elif kind == 'content_mismatch':
                        states.append('pass' if intent.allow_integrity_retry else 'mismatch')
                    else:
                        states.append('unknown')
                else:
                    states.append('unknown')
                reasons.append({'id': a['id'], 'verdict': states[-1], 'role': role,
                                'owner': a.get('owner'), 'retry_of': a.get('retry_of'), 'cause': a.get('cause')})
        if record.get('arrival_stream_complete') is not True or record.get('retry_attribution_complete') is not True:
            states.append('unknown')
        # An observed empty, fully attributed operation performs no retry.
        if not states and valid_arrivals:
            states.append('pass')
        put('classification', combine(states), 'explicit retry ownership and received cause; no adjacent-status inference', requests=reasons)

    if intent.budget_s is not None:
        limit = intent.budget_s + intent.tolerance_s
        if intent.time_scope == 'operation':
            elapsed = record.get(f'{intent.boundary}_elapsed_s')
            terminal = record.get(f'{intent.boundary}_complete') is True
            if not finite_nonnegative(elapsed):
                put('time', 'unknown', 'missing or non-finite boundary duration')
            elif elapsed > limit:
                put('time', 'mismatch', 'observed duration or prefix already exceeds budget', observed=elapsed, limit=limit, boundary=intent.boundary)
            elif not terminal:
                put('time', 'unknown', 'boundary has not completed')
            else:
                put('time', 'pass', 'observed boundary completed within tolerance', observed=elapsed, limit=limit, boundary=intent.boundary)
        else:
            admissions = record.get('admissions_s')
            if not isinstance(admissions, list) or any(not finite_nonnegative(t) for t in admissions) or admissions != sorted(admissions):
                put('admission', 'unknown', 'missing or malformed client-side admission timestamps')
            elif any(t > limit for t in admissions[1:]):
                put('admission', 'mismatch', 'witnessed late client-side retry admission', observed=admissions)
            elif record.get('admissions_complete') is not True:
                put('admission', 'unknown', 'admission sequence is only a prefix')
            else:
                put('admission', 'pass', 'complete client-side admission sequence fits budget')
    return {'schema': 2, 'verdict': combine([d['verdict'] for d in dimensions.values()]),
            'dimensions': dimensions, 'intent_provenance': intent.provenance,
            'hard_deadline_guarantee': False}


def from_legacy(record: Mapping[str, Any]) -> dict[str, Any]:
    """Convert recorded facts only; do not manufacture client-received causes.

    The legacy fixture's planned status/body_fault fields cannot establish which
    cause was actually observed by a retry owner. Classification remains unknown.
    """
    out = {'outcome': record.get('outcome'), 'payload': record.get('payload'),
           'payload_complete': record.get('outcome') == 'success' and record.get('config', {}).get('mode') != 'headers_only',
           'body_elapsed_s': record.get('elapsed_s'), 'body_complete': record.get('trace_complete') is True,
           'headers_elapsed_s': record.get('headers_elapsed_s'), 'headers_complete': record.get('headers_elapsed_s') is not None,
           'cleanup_elapsed_s': record.get('elapsed_s'), 'cleanup_complete': record.get('trace_complete') is True,
           'arrival_stream_complete': record.get('trace_complete') is True,
           'retry_attribution_complete': False}
    if isinstance(record.get('events'), list):
        out['arrivals'] = [{'id': e.get('index'), 't': e.get('t')} for e in record['events'] if e.get('kind') == 'arrival']
    return out
