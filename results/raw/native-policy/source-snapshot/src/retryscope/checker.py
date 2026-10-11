"""A small trace oracle. A passing finite trace is not a universal guarantee."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any, Literal
import math

@dataclass(frozen=True)
class Intent:
    max_wire_attempts: int | None = None
    retryable_statuses: tuple[int, ...] | None = None
    allow_body_recovery: bool = False
    allow_transport_retry: bool = False
    expected_payload_on_success: str | None = None
    required_outcome: str | None = None
    budget_s: float | None = None
    time_scope: Literal["observation", "operation", "admission"] = "observation"
    boundary: Literal["headers", "body"] = "body"
    provenance: str = "researcher-authored local application test"
    tolerance_s: float = 0.020

    def __post_init__(self):
        if self.max_wire_attempts is not None and not 1 <= self.max_wire_attempts <= 16:
            raise ValueError("max_wire_attempts must be 1..16 or None")
        if self.budget_s is not None and (not math.isfinite(self.budget_s) or self.budget_s <= 0):
            raise ValueError("budget_s must be finite and positive")
        if self.tolerance_s < 0 or not math.isfinite(self.tolerance_s):
            raise ValueError("invalid tolerance")
        if self.time_scope not in ("observation", "operation", "admission"):
            raise ValueError("unknown time scope")
        if self.boundary not in ("headers", "body"):
            raise ValueError("unknown operation boundary")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def check(record: dict[str, Any], intent: Intent) -> dict[str, Any]:
    """Check witnessed behavior, abstaining when an oracle/trace is missing.

    Retry classification is identifiable only for this sequential single-operation
    responder: each additional request follows the immediately preceding response.
    The general application case needs an explicit parent/operation identifier.
    """
    events = record.get("events", [])
    arrivals = [e for e in events if e.get("kind") == "arrival"]
    arrivals.sort(key=lambda e: e["t"])
    findings: list[dict[str, Any]] = []
    specified = 0
    complete = record.get("trace_complete", False)
    if not complete:
        return {"verdict": "unknown", "findings": [], "reason": "incomplete trace", "wire_attempts": len(arrivals)}
    if intent.max_wire_attempts is not None:
        specified += 1
        if len(arrivals) > intent.max_wire_attempts:
            findings.append({"dimension": "attempts", "observed": len(arrivals), "limit": intent.max_wire_attempts})
    if intent.retryable_statuses is not None:
        specified += 1
        for previous, current in zip(arrivals, arrivals[1:]):
            body_recovery = previous.get("body_fault", False) and intent.allow_body_recovery
            # A planned response is not necessarily received: a header delay can
            # cause a timeout before its status reaches the client.
            transport_failure = previous.get("header_delay", 0) > record.get("read_timeout_s", float("inf"))
            if previous["status"] not in intent.retryable_statuses and not body_recovery and not (transport_failure and intent.allow_transport_retry):
                findings.append({"dimension": "classification", "after_attempt": previous["index"], "status": previous["status"]})
    if intent.expected_payload_on_success is not None:
        specified += 1
        if record.get("outcome") == "success" and record.get("payload") != intent.expected_payload_on_success:
            findings.append({"dimension": "payload", "observed": record.get("payload"), "expected": intent.expected_payload_on_success})
    if intent.required_outcome is not None:
        specified += 1
        if record.get("outcome") != intent.required_outcome:
            findings.append({"dimension": "outcome", "observed": record.get("outcome"), "expected": intent.required_outcome})
    if intent.budget_s is not None and intent.time_scope != "observation":
        specified += 1
        if intent.time_scope == "operation":
            elapsed = record.get("headers_elapsed_s") if intent.boundary == "headers" else record.get("elapsed_s")
            if elapsed is None:
                return {"verdict": "unknown", "findings": findings, "reason": "missing operation end", "wire_attempts": len(arrivals)}
            if elapsed > intent.budget_s + intent.tolerance_s:
                findings.append({"dimension": "time", "observed": elapsed, "limit": intent.budget_s, "tolerance": intent.tolerance_s})
        else:
            late = [a["index"] for a in arrivals[1:] if a["t"] - record["start_t"] > intent.budget_s + intent.tolerance_s]
            if late:
                findings.append({"dimension": "admission", "late_attempts": late})
    return {
        "verdict": "mismatch" if findings else ("pass" if specified else "unknown"),
        "findings": findings, "wire_attempts": len(arrivals),
        "hard_deadline_guarantee": False,
        "capability": "finite-trace observation; no DNS/connect/read interruption guarantee",
    }


def compare(before: dict[str, Any], after: dict[str, Any], intent: Intent) -> dict[str, Any]:
    a, b = check(before, intent), check(after, intent)
    return {"before": a, "after": b,
            "transition": f"{a['verdict']} -> {b['verdict']}",
            "interpretation": "conformance change, not automatic library-defect attribution"}
