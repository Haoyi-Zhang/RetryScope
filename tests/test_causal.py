from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor

import pytest

from retryscope.audit import AuditIntent, audit
from retryscope.causal import (
    WitnessLedger,
    deterministic_operation_id,
    expected_edge_set,
    join_causal_trace,
    parse_wire_headers,
)


def arrival(ticket, global_index=1):
    return {
        "kind": "arrival",
        "global_index": global_index,
        "operation_index": ticket.ordinal,
        "ordinal": ticket.ordinal,
        "operation_id": ticket.operation_id,
        "attempt_id": ticket.attempt_id,
        "witness_valid": True,
    }


def test_headers_cross_check_trace_context():
    ledger = WitnessLedger(deterministic_operation_id("headers"))
    ticket = ledger.admit(role="initial", owner="client", nonce="a")
    parsed = parse_wire_headers(ledger.headers(ticket))
    assert parsed == {
        "operation_id": ledger.operation_id,
        "attempt_id": ticket.attempt_id,
        "ordinal": 1,
        "traceparent": f"00-{ledger.operation_id}-{ticket.attempt_id}-01",
        "valid": True,
        "errors": [],
    }


def test_retry_requires_same_ledger_parent_and_cause():
    left = WitnessLedger(deterministic_operation_id("left"))
    right = WitnessLedger(deterministic_operation_id("right"))
    initial = left.admit(role="initial", owner="client")
    with pytest.raises(ValueError, match="parent"):
        right.admit(role="retry", owner="client", parent=initial, cause={"kind": "status", "received_status": 503})
    with pytest.raises(ValueError, match="cause"):
        left.admit(role="retry", owner="client", parent=initial)


def test_exact_join_builds_audit_compatible_retry_edge():
    ledger = WitnessLedger(deterministic_operation_id("join"))
    first = ledger.admit(role="initial", owner="requests", nonce="first")
    second = ledger.admit(
        role="retry",
        owner="urllib3",
        parent=first,
        cause={"kind": "status", "received_status": 503},
        nonce="second",
    )
    trace = join_causal_trace(
        ledger.events,
        [arrival(first, 1), arrival(second, 2)],
        operation_id=ledger.operation_id,
        outcome="success",
        payload="ok",
        elapsed_s=0.01,
    )
    assert trace["causal_join_complete"] is True
    assert trace["arrivals"][1]["retry_of"] == 1
    assert trace["arrivals"][1]["owner"] == "urllib3"
    result = audit(trace, AuditIntent(max_wire_attempts=2, retryable_statuses=(503,), required_outcome="success"))
    assert result["verdict"] == "pass"


def test_recovery_role_uses_body_recovery_contract():
    ledger = WitnessLedger(deterministic_operation_id("recovery"))
    first = ledger.admit(role="initial", owner="reader")
    second = ledger.admit(
        role="recovery",
        owner="reader",
        parent=first,
        cause={"kind": "body_error", "exception": "IncompleteRead"},
    )
    trace = join_causal_trace(ledger.events, [arrival(first), arrival(second, 2)], operation_id=ledger.operation_id)
    assert audit(trace, AuditIntent(retryable_statuses=(), allow_body_recovery=True))["verdict"] == "pass"
    assert audit(trace, AuditIntent(retryable_statuses=(), allow_body_recovery=False))["verdict"] == "mismatch"


def test_missing_wire_attempt_abstains_but_count_inventory_remains():
    ledger = WitnessLedger(deterministic_operation_id("missing"))
    first = ledger.admit(role="initial", owner="client")
    ledger.admit(role="retry", owner="client", parent=first, cause={"kind": "status", "received_status": 503})
    trace = join_causal_trace(ledger.events, [arrival(first)], operation_id=ledger.operation_id)
    assert trace["causal_join_complete"] is False
    assert len(trace["unmatched_client_admissions"]) == 1
    assert audit(trace, AuditIntent(max_wire_attempts=2))["dimensions"]["attempts"]["verdict"] == "pass"
    assert audit(trace, AuditIntent(retryable_statuses=(503,)))["verdict"] == "unknown"


def test_duplicate_wire_token_is_rejected():
    ledger = WitnessLedger(deterministic_operation_id("duplicate"))
    first = ledger.admit(role="initial", owner="client")
    trace = join_causal_trace(ledger.events, [arrival(first), arrival(first, 2)], operation_id=ledger.operation_id)
    assert trace["causal_join_complete"] is False
    assert any("duplicate wire arrival" in error for error in trace["causal_errors"])


def test_cross_operation_arrivals_do_not_contaminate_join():
    a = WitnessLedger(deterministic_operation_id("a"))
    b = WitnessLedger(deterministic_operation_id("b"))
    at = a.admit(role="initial", owner="a")
    bt = b.admit(role="initial", owner="b")
    trace = join_causal_trace(a.events + b.events, [arrival(bt), arrival(at, 2)], operation_id=a.operation_id)
    assert trace["causal_join_complete"] is True
    assert [row["attempt_id"] for row in trace["arrivals"]] == [at.attempt_id]


def test_expected_edges_are_concurrency_safe():
    operation_id = deterministic_operation_id("concurrent-ledger")
    ledger = WitnessLedger(operation_id)
    root = ledger.admit(role="initial", owner="root")

    def add(index):
        return ledger.admit(
            role="retry",
            owner=f"worker-{index}",
            parent=root,
            cause={"kind": "transport_error", "index": index},
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        tickets = list(pool.map(add, range(8)))
    assert len({ticket.ordinal for ticket in tickets}) == 8
    assert len({ticket.attempt_id for ticket in tickets}) == 8
    assert len(expected_edge_set(ledger.events, operation_id)) == 8


def test_parent_tampering_is_detected():
    ledger = WitnessLedger(deterministic_operation_id("tamper"))
    first = ledger.admit(role="initial", owner="client")
    second = ledger.admit(role="retry", owner="client", parent=first, cause={"kind": "status", "received_status": 503})
    events = copy.deepcopy(ledger.events)
    for event in events:
        if event.get("attempt_id") == second.attempt_id:
            event["parent_attempt_id"] = "f" * 16
    trace = join_causal_trace(events, [arrival(first), arrival(second, 2)], operation_id=ledger.operation_id)
    assert trace["causal_join_complete"] is False
    assert any("missing parent" in error for error in trace["causal_errors"])


def test_duplicate_completion_is_rejected():
    ledger = WitnessLedger(deterministic_operation_id("duplicate-completion"))
    ticket = ledger.admit(role="initial", owner="client")
    ledger.complete(ticket, status=200, bytes_read=2)
    with pytest.raises(ValueError, match="already completed"):
        ledger.complete(ticket, status=200, bytes_read=2)


def test_malformed_other_operation_does_not_poison_join():
    a = WitnessLedger(deterministic_operation_id("scope-a"))
    b = WitnessLedger(deterministic_operation_id("scope-b"))
    at = a.admit(role="initial", owner="a")
    bt = b.admit(role="initial", owner="b")
    other = arrival(bt)
    other["witness_valid"] = False
    trace = join_causal_trace(a.events + b.events, [other, arrival(at, 2)], operation_id=a.operation_id)
    assert trace["causal_join_complete"] is True
    assert trace["causal_errors"] == []


def test_empty_operation_evidence_fails_closed():
    operation_id = deterministic_operation_id("empty-operation")
    trace = join_causal_trace([], [], operation_id=operation_id)
    assert trace["causal_join_complete"] is False
    assert "operation has no valid client admissions" in trace["causal_errors"]
    assert "operation has no valid wire arrivals" in trace["causal_errors"]


def test_corrupted_operation_identifier_cannot_disappear_silently():
    ledger = WitnessLedger(deterministic_operation_id("corrupted-operation"))
    ticket = ledger.admit(role="initial", owner="client")
    corrupted = arrival(ticket)
    corrupted["operation_id"] = deterministic_operation_id("other-operation")
    trace = join_causal_trace(ledger.events, [corrupted], operation_id=ledger.operation_id)
    assert trace["causal_join_complete"] is False
    assert trace["unmatched_client_admissions"] == [ticket.attempt_id]
    assert "operation has no valid wire arrivals" in trace["causal_errors"]
