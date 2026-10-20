"""Concurrency-safe causal witnesses for retry-migration tests.

The existing timestamp join is useful for a single sequential operation, but it
cannot distinguish interleaved operations without extra context.  This module
adds a small, explicit witness protocol:

* every logical operation has an opaque 128-bit operation identifier;
* every admitted wire request has an opaque 64-bit attempt identifier;
* the client records role, owner, parent attempt, and observed cause at the
  decision point;
* the loopback responder records only the operation/attempt identifiers carried
  by the request; and
* an offline join accepts a retry edge only when the independent client and wire
  records agree on both identifiers.

The protocol is intentionally narrower than general distributed tracing.  It is
for bounded, read-only migration tests and does not make a production request
safe, idempotent, or cancellable.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from copy import deepcopy
from hashlib import sha256
import re
import secrets
import threading
import time
from typing import Any, Iterable, Mapping

_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")
_SPAN_ID = re.compile(r"^[0-9a-f]{16}$")
_ALLOWED_ROLES = {"initial", "retry", "constituent", "recovery"}
_HEADER_OPERATION = "x-retryscope-operation"
_HEADER_ATTEMPT = "x-retryscope-attempt"
_HEADER_ORDINAL = "x-retryscope-ordinal"


def _valid_trace_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_TRACE_ID.fullmatch(value)) and value != "0" * 32


def _valid_span_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_SPAN_ID.fullmatch(value)) and value != "0" * 16


def deterministic_operation_id(label: str) -> str:
    """Create a stable non-zero 128-bit identifier for a reproducible study case."""
    if not isinstance(label, str) or not label:
        raise ValueError("label must be a non-empty string")
    value = sha256(label.encode("utf-8")).hexdigest()[:32]
    return value if value != "0" * 32 else "1" + value[1:]


def _new_operation_id() -> str:
    value = secrets.token_hex(16)
    return value if value != "0" * 32 else "1" + value[1:]


def _attempt_id(operation_id: str, ordinal: int, nonce: str) -> str:
    value = sha256(f"{operation_id}:{ordinal}:{nonce}".encode("utf-8")).hexdigest()[:16]
    return value if value != "0" * 16 else "1" + value[1:]


@dataclass(frozen=True)
class AttemptTicket:
    operation_id: str
    attempt_id: str
    ordinal: int
    role: str
    owner: str
    parent_attempt_id: str | None = None
    cause: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WitnessLedger:
    """Thread-safe append-only client witness ledger for one logical operation."""

    def __init__(self, operation_id: str | None = None) -> None:
        operation_id = operation_id or _new_operation_id()
        if not _valid_trace_id(operation_id):
            raise ValueError("operation_id must be a non-zero 32-character lowercase hex value")
        self.operation_id = operation_id
        self._lock = threading.RLock()
        self._next_ordinal = 1
        self._tickets: dict[str, AttemptTicket] = {}
        self._completed: set[str] = set()
        self._events: list[dict[str, Any]] = []
        self._sequence = 0

    def _append(self, event: dict[str, Any]) -> None:
        self._sequence += 1
        self._events.append({"seq": self._sequence, "t_ns": time.monotonic_ns(), **event})

    def _check_ticket(self, ticket: AttemptTicket) -> AttemptTicket:
        with self._lock:
            canonical = self._tickets.get(ticket.attempt_id)
            if canonical is None or ticket != canonical:
                raise ValueError('ticket fields do not match this ledger')
            return canonical

    def admit(
        self,
        *,
        role: str,
        owner: str,
        parent: AttemptTicket | str | None = None,
        cause: Mapping[str, Any] | None = None,
        nonce: str = "",
    ) -> AttemptTicket:
        """Admit one request and record its causal role before any wire I/O.

        ``retry`` and ``recovery`` require a parent and a witnessed cause.
        ``initial`` and ``constituent`` must not claim a parent.  The returned
        ticket is a caller-owned snapshot; changing nested cause data cannot
        change the ledger or a snapshot returned to another caller.
        """
        if role not in _ALLOWED_ROLES:
            raise ValueError(f"unsupported role: {role}")
        if not isinstance(owner, str) or not owner.strip() or len(owner) > 128:
            raise ValueError("owner must be a non-empty string of at most 128 characters")
        parent_id = parent.attempt_id if isinstance(parent, AttemptTicket) else parent
        with self._lock:
            if isinstance(parent, AttemptTicket):
                try:
                    self._check_ticket(parent)
                except ValueError as exc:
                    raise ValueError('parent ticket does not match this ledger') from exc
            if role in {"retry", "recovery"}:
                if not _valid_span_id(parent_id) or parent_id not in self._tickets:
                    raise ValueError(f"{role} requires a parent from the same ledger")
                if not isinstance(cause, Mapping) or not cause.get("kind"):
                    raise ValueError(f"{role} requires an observed cause")
            elif parent_id is not None:
                raise ValueError(f"{role} cannot claim a parent attempt")
            ordinal = self._next_ordinal
            self._next_ordinal += 1
            attempt_id = _attempt_id(self.operation_id, ordinal, nonce or secrets.token_hex(4))
            # The deterministic hash can collide only if callers deliberately reuse
            # the same nonce for the same ordinal; reject rather than silently merge.
            if attempt_id in self._tickets:
                raise ValueError("duplicate attempt identifier")
            ticket = AttemptTicket(
                operation_id=self.operation_id,
                attempt_id=attempt_id,
                ordinal=ordinal,
                role=role,
                owner=owner.strip(),
                parent_attempt_id=parent_id,
                cause=deepcopy(dict(cause)) if cause is not None else None,
            )
            self._tickets[attempt_id] = deepcopy(ticket)
            self._append({"kind": "admission", **ticket.to_dict()})
            return ticket

    def complete(
        self,
        ticket: AttemptTicket,
        *,
        status: int | None = None,
        error: BaseException | str | None = None,
        bytes_read: int | None = None,
    ) -> None:
        ticket = self._check_ticket(ticket)
        if status is not None and (isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599):
            raise ValueError("status must be an HTTP status")
        if bytes_read is not None and (isinstance(bytes_read, bool) or not isinstance(bytes_read, int) or bytes_read < 0):
            raise ValueError("bytes_read must be a non-negative integer")
        if isinstance(error, BaseException):
            error_value: str | None = f"{type(error).__module__}.{type(error).__name__}"
        elif error is None or isinstance(error, str):
            error_value = error
        else:
            raise ValueError("error must be an exception, string, or None")
        with self._lock:
            if ticket.attempt_id in self._completed:
                raise ValueError("attempt already completed")
            self._completed.add(ticket.attempt_id)
            self._append(
                {
                    "kind": "completion",
                    "operation_id": self.operation_id,
                    "attempt_id": ticket.attempt_id,
                    "ordinal": ticket.ordinal,
                    "status": status,
                    "error": error_value,
                    "bytes_read": bytes_read,
                }
            )

    def headers(self, ticket: AttemptTicket) -> dict[str, str]:
        """Return bounded loopback headers plus a standards-shaped traceparent.

        The custom headers are the study's exact join keys.  ``traceparent`` is
        emitted to make interoperability experiments possible, but RetryScope
        does not claim to be a complete OpenTelemetry implementation.
        """
        ticket = self._check_ticket(ticket)
        return {
            "traceparent": f"00-{ticket.operation_id}-{ticket.attempt_id}-01",
            _HEADER_OPERATION: ticket.operation_id,
            _HEADER_ATTEMPT: ticket.attempt_id,
            _HEADER_ORDINAL: str(ticket.ordinal),
        }

    @property
    def events(self) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(self._events)

    @property
    def tickets(self) -> tuple[AttemptTicket, ...]:
        with self._lock:
            return tuple(deepcopy(sorted(self._tickets.values(), key=lambda ticket: ticket.ordinal)))


def parse_wire_headers(headers: Mapping[str, Any]) -> dict[str, Any]:
    """Parse and cross-check the bounded witness headers from an HTTP request."""
    lowered = {str(key).lower(): str(value) for key, value in headers.items()}
    operation_id = lowered.get(_HEADER_OPERATION)
    attempt_id = lowered.get(_HEADER_ATTEMPT)
    ordinal_text = lowered.get(_HEADER_ORDINAL)
    traceparent = lowered.get("traceparent")
    errors: list[str] = []
    if not _valid_trace_id(operation_id):
        errors.append("invalid operation identifier")
    if not _valid_span_id(attempt_id):
        errors.append("invalid attempt identifier")
    try:
        ordinal = int(ordinal_text) if ordinal_text is not None else None
    except ValueError:
        ordinal = None
    if ordinal is None or ordinal < 1 or ordinal > 16:
        errors.append("invalid ordinal")
    expected_traceparent = (
        f"00-{operation_id}-{attempt_id}-01"
        if _valid_trace_id(operation_id) and _valid_span_id(attempt_id)
        else None
    )
    if expected_traceparent is None or traceparent != expected_traceparent:
        errors.append("traceparent does not agree with witness identifiers")
    return {
        "operation_id": operation_id,
        "attempt_id": attempt_id,
        "ordinal": ordinal,
        "traceparent": traceparent,
        "valid": not errors,
        "errors": errors,
    }


def _admissions(events: Iterable[Mapping[str, Any]]) -> tuple[dict[tuple[str, str], dict[str, Any]], list[str]]:
    admissions: dict[tuple[str, str], dict[str, Any]] = {}
    errors: list[str] = []
    for raw in events:
        if raw.get("kind") != "admission":
            continue
        event = dict(raw)
        operation_id = event.get("operation_id")
        attempt_id = event.get("attempt_id")
        key = (operation_id, attempt_id)
        if not _valid_trace_id(operation_id) or not _valid_span_id(attempt_id):
            errors.append("malformed client admission identifier")
            continue
        if key in admissions:
            errors.append(f"duplicate client admission {operation_id}/{attempt_id}")
            continue
        if event.get("role") not in _ALLOWED_ROLES:
            errors.append(f"invalid role for {operation_id}/{attempt_id}")
            continue
        owner = event.get("owner")
        if not isinstance(owner, str) or not owner.strip() or len(owner) > 128:
            errors.append(f"invalid owner for {operation_id}/{attempt_id}")
            continue
        if event["role"] in {"retry", "recovery"}:
            cause = event.get("cause")
            if not isinstance(cause, Mapping) or not isinstance(cause.get("kind"), str) or not cause["kind"]:
                errors.append(f"missing cause for {operation_id}/{attempt_id}")
                continue
        ordinal = event.get("ordinal")
        if isinstance(ordinal, bool) or not isinstance(ordinal, int) or not 1 <= ordinal <= 16:
            errors.append(f"invalid ordinal for {operation_id}/{attempt_id}")
            continue
        admissions[key] = event
    return admissions, errors


def _wire_arrivals(events: Iterable[Mapping[str, Any]]) -> tuple[dict[tuple[str, str], dict[str, Any]], list[str]]:
    arrivals: dict[tuple[str, str], dict[str, Any]] = {}
    ambiguous: set[tuple[str, str]] = set()
    errors: list[str] = []
    for raw in events:
        if raw.get("kind") != "arrival":
            continue
        event = dict(raw)
        operation_id = event.get("operation_id")
        attempt_id = event.get("attempt_id")
        key = (operation_id, attempt_id)
        if not _valid_trace_id(operation_id) or not _valid_span_id(attempt_id):
            errors.append("wire arrival lacks valid witness identifiers")
            continue
        if event.get("witness_valid") is not True:
            errors.append(f"wire witness validation failed for {operation_id}/{attempt_id}")
            continue
        if key in arrivals or key in ambiguous:
            errors.append(f"duplicate wire arrival {operation_id}/{attempt_id}")
            arrivals.pop(key, None)
            ambiguous.add(key)
            continue
        arrivals[key] = event
    return arrivals, errors


def _validate_parents(operation_events: list[dict[str, Any]]) -> list[str]:
    by_attempt = {event["attempt_id"]: event for event in operation_events}
    errors: list[str] = []
    for event in operation_events:
        role = event["role"]
        parent = event.get("parent_attempt_id")
        if role in {"retry", "recovery"}:
            parent_event = by_attempt.get(parent)
            if parent_event is None:
                errors.append(f"missing parent for attempt {event['attempt_id']}")
            elif parent_event["ordinal"] >= event["ordinal"]:
                errors.append(f"non-causal parent ordering for attempt {event['attempt_id']}")
        elif parent is not None:
            errors.append(f"unexpected parent for {role} attempt {event['attempt_id']}")
    # Parent ordering already forbids cycles, but retain an explicit walk so a
    # future schema change cannot accidentally weaken the invariant.
    for event in operation_events:
        seen: set[str] = set()
        current = event
        while current.get("parent_attempt_id") is not None:
            parent = current["parent_attempt_id"]
            if parent in seen:
                errors.append(f"cycle involving attempt {parent}")
                break
            seen.add(parent)
            current = by_attempt.get(parent, {})
            if not current:
                break
    return errors


def join_causal_trace(
    client_events: Iterable[Mapping[str, Any]],
    wire_events: Iterable[Mapping[str, Any]],
    *,
    operation_id: str,
    stream_complete: bool = True,
    outcome: str | None = None,
    payload: str | None = None,
    payload_complete: bool | None = None,
    elapsed_s: float | None = None,
    headers_elapsed_s: float | None = None,
    headers_complete: bool = False,
    body_elapsed_s: float | None = None,
    body_complete: bool = False,
    cleanup_elapsed_s: float | None = None,
    cleanup_complete: bool = False,
) -> dict[str, Any]:
    """Join client admissions and wire arrivals by exact operation/attempt IDs.

    Malformed, duplicated, cross-operation, or parent-inconsistent evidence is
    retained in ``causal_errors`` and causes attribution to abstain.  The returned
    request inventory remains usable for independent count checks.
    """
    if not _valid_trace_id(operation_id):
        raise ValueError("operation_id must be a valid non-zero trace identifier")
    # Scope parsing to the requested operation.  A malformed record from a
    # different concurrent operation must not poison this operation's verdict;
    # a corrupted identifier for this operation is still exposed by the missing
    # admission/arrival checks below.
    client_records = [dict(event) for event in client_events]
    wire_records = [dict(event) for event in wire_events]
    observed_wire = [event for event in wire_records
                     if event.get("kind") == "arrival" and event.get("operation_id") == operation_id]
    inventory: dict[int, dict[str, Any]] = {}
    inventory_complete = True
    for event in observed_wire:
        physical_id = event.get('global_index')
        if type(physical_id) is not int or physical_id < 1:
            inventory_complete = False
            continue
        if physical_id in inventory and inventory[physical_id] != event:
            inventory_complete = False
        else:
            inventory[physical_id] = event
    scoped_wire = list(inventory.values())
    admissions, client_errors = _admissions(
        event for event in client_records if event.get("operation_id") == operation_id
    )
    arrivals, wire_errors = _wire_arrivals(
        event for event in scoped_wire
    )
    operation_admissions = [
        dict(event)
        for (op, _), event in admissions.items()
        if op == operation_id
    ]
    operation_admissions.sort(key=lambda event: event["ordinal"])
    parent_errors = _validate_parents(operation_admissions)

    joined: list[dict[str, Any]] = []
    join_errors: list[str] = []
    unmatched_wire = 0
    matched_attempt_ids: set[str] = set()
    for (op, attempt_id), wire in sorted(
        arrivals.items(), key=lambda item: (item[1].get("global_index", 0), item[1].get("t_ns", 0))
    ):
        if op != operation_id:
            continue
        admission = admissions.get((op, attempt_id))
        if admission is None:
            unmatched_wire += 1
            joined.append(
                {
                    "id": wire.get("operation_index", wire.get("global_index")),
                    "attempt_id": attempt_id,
                    "role": "unknown",
                    "attribution_witness": None,
                }
            )
            continue
        if wire.get('ordinal') != admission['ordinal']:
            join_errors.append(f"conflicting ordinal for {op}/{attempt_id}")
        matched_attempt_ids.add(attempt_id)
        parent = admission.get("parent_attempt_id")
        parent_ordinal = admissions.get((op, parent), {}).get("ordinal") if parent else None
        role = admission["role"]
        row: dict[str, Any] = {
            "id": admission["ordinal"],
            "attempt_id": attempt_id,
            "t": wire.get("t"),
            "role": role,
            "owner": admission.get("owner"),
            "attribution_witness": "exact client/wire operation-and-attempt token join",
        }
        if parent_ordinal is not None:
            row["retry_of"] = parent_ordinal
        if admission.get("cause") is not None:
            row["cause"] = dict(admission["cause"])
        joined.append(row)

    unmatched_admissions = [
        event["attempt_id"] for event in operation_admissions if event["attempt_id"] not in matched_attempt_ids
    ]
    ordinal_values = [row.get("id") for row in joined if isinstance(row.get("id"), int)]
    inventory_unique = len(ordinal_values) == len(set(ordinal_values))
    causal_errors = client_errors + wire_errors + parent_errors + join_errors
    if not inventory_complete:
        causal_errors.append("physical arrival inventory is incomplete or conflicting")
    if not operation_admissions:
        causal_errors.append("operation has no valid client admissions")
    if not any(op == operation_id for op, _attempt in arrivals):
        causal_errors.append("operation has no valid wire arrivals")
    complete = (
        stream_complete
        and inventory_complete
        and not causal_errors
        and unmatched_wire == 0
        and not unmatched_admissions
        and inventory_unique
        and len(joined) == len(operation_admissions)
    )
    edges = [
        {
            "parent_attempt_id": event.get("parent_attempt_id"),
            "attempt_id": event["attempt_id"],
            "role": event["role"],
            "owner": event.get("owner"),
        }
        for event in operation_admissions
        if event.get("parent_attempt_id") in matched_attempt_ids
        and event["attempt_id"] in matched_attempt_ids
    ]
    trace = {
        "schema": 4,
        "operation_id": operation_id,
        "arrivals": sorted(joined, key=lambda row: (row.get("id") is None, row.get("id", 10**9))),
        "wire_inventory": scoped_wire,
        "wire_attempts_observed": len(inventory),
        "arrival_stream_complete": bool(stream_complete) and inventory_complete,
        "retry_attribution_complete": complete,
        "causal_join_complete": complete,
        "causal_edges": edges,
        "causal_errors": causal_errors,
        "unmatched_wire_arrivals": unmatched_wire,
        "unmatched_client_admissions": unmatched_admissions,
        "outcome": outcome,
        "payload": payload,
        "payload_complete": payload_complete is True,
        "elapsed_s": elapsed_s,
        "headers_elapsed_s": headers_elapsed_s,
        "headers_complete": headers_complete is True,
        "body_elapsed_s": body_elapsed_s,
        "body_complete": body_complete is True,
        "cleanup_elapsed_s": cleanup_elapsed_s,
        "cleanup_complete": cleanup_complete is True,
        "observation_scope": "operation/attempt token join supports interleaved bounded loopback operations",
    }
    return trace


def expected_edge_set(client_events: Iterable[Mapping[str, Any]], operation_id: str) -> set[tuple[str, str, str, str]]:
    """Return the declared causal edges for evaluation and consistency checks."""
    admissions, errors = _admissions(client_events)
    if errors:
        raise ValueError("malformed client events: " + "; ".join(errors))
    return {
        (event["parent_attempt_id"], event["attempt_id"], event["role"], event["owner"])
        for (op, _), event in admissions.items()
        if op == operation_id and event.get("parent_attempt_id") is not None
    }
