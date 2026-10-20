"""Paired, evidence-aware migration comparisons.

The module compares two finite operation traces under the *same* explicit intent.
It separates behavioral conformance from observation coverage: a library change may
preserve the verdict while changing wire work, and an instrumentation change may
turn a previously decidable dimension into ``unknown`` without establishing a
behavior regression.
"""
from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from typing import Any, Mapping

from .audit import AuditIntent, audit


_DIMENSION_OBLIGATIONS: dict[str, tuple[str, ...]] = {
    "attempts": ("arrivals", "arrival_stream_complete"),
    "outcome": ("outcome",),
    "payload": ("outcome", "payload", "payload_complete"),
    "classification": ("arrivals", "arrival_stream_complete", "retry_attribution_complete"),
    "time": ("boundary_elapsed", "boundary_complete"),
    "admission": ("admissions_s", "admissions_complete"),
}


def intent_fingerprint(intent: AuditIntent) -> str:
    """Return a stable identifier for exact intent equality."""
    payload = json.dumps(asdict(intent), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(payload.encode("utf-8")).hexdigest()


def required_dimensions(intent: AuditIntent) -> tuple[str, ...]:
    dims: list[str] = []
    if intent.max_wire_attempts is not None:
        dims.append("attempts")
    if intent.required_outcome is not None:
        dims.append("outcome")
    if intent.expected_payload is not None:
        dims.append("payload")
    if intent.retryable_statuses is not None:
        dims.append("classification")
    if intent.budget_s is not None:
        dims.append("time" if intent.time_scope == "operation" else "admission")
    return tuple(dims)


def evidence_obligations(intent: AuditIntent) -> dict[str, list[str]]:
    """Describe the minimum trace fields needed for each requested dimension.

    This is a documentation and CI aid, not a proof that a field is truthful. The
    audit still validates types, completeness flags, and request-level witnesses.
    """
    out: dict[str, list[str]] = {}
    for dim in required_dimensions(intent):
        fields = list(_DIMENSION_OBLIGATIONS[dim])
        if dim == "time":
            fields = [f"{intent.boundary}_elapsed_s", f"{intent.boundary}_complete"]
        out[dim] = fields
    return out


def evidence_report(record: Mapping[str, Any], intent: AuditIntent) -> dict[str, Any]:
    result = audit(record, intent)
    required = evidence_obligations(intent)
    dimensions: dict[str, Any] = {}
    for name in required:
        observed = result["dimensions"].get(name)
        dimensions[name] = {
            "verdict": observed["verdict"] if observed else "unknown",
            "reason": observed["reason"] if observed else "dimension was not evaluated",
            "obligations": required[name],
        }
    return {
        "required_dimensions": list(required),
        "decidable_dimensions": sum(1 for row in dimensions.values() if row["verdict"] != "unknown"),
        "dimensions": dimensions,
    }


def _transition(before: str, after: str) -> str:
    if before == "pass" and after == "mismatch":
        return "regression"
    if before == "mismatch" and after == "pass":
        return "repair"
    if before == "pass" and after == "pass":
        return "stable_conformant"
    if before == "mismatch" and after == "mismatch":
        return "stable_nonconformant"
    if before != "unknown" and after == "unknown":
        return "evidence_loss"
    if before == "unknown" and after != "unknown":
        return "evidence_gain"
    return "inconclusive"


def _compact_observation(audit_result: Mapping[str, Any]) -> dict[str, Any]:
    """Extract non-sensitive, dimension-level observations for a paired diff."""
    out: dict[str, Any] = {}
    for name, row in audit_result.get("dimensions", {}).items():
        selected = {k: row[k] for k in ("observed", "limit", "boundary") if k in row}
        if name == "classification" and "requests" in row:
            selected["request_verdicts"] = [
                {k: item.get(k) for k in ("id", "role", "owner", "verdict") if k in item}
                for item in row["requests"]
            ]
        out[name] = selected
    return out



def _structural_summary(record: Mapping[str, Any]) -> dict[str, Any]:
    arrivals = record.get("arrivals")
    wire = len(arrivals) if isinstance(arrivals, list) else record.get("wire_attempts")
    payload = record.get("payload")
    if isinstance(payload, str):
        payload_value: Any = {"sha256": sha256(payload.encode("utf-8")).hexdigest(), "length": len(payload)}
    else:
        payload_value = None
    requests = [{key: row.get(key) for key in ('id', 'role', 'owner', 'retry_of', 'cause')}
                for row in arrivals] if isinstance(arrivals, list) else None
    boundaries = {key: record.get(key) for boundary in ('headers', 'body', 'cleanup')
                  for key in (f'{boundary}_elapsed_s', f'{boundary}_complete')}
    return {"wire_attempts": record.get('wire_attempts_observed', wire),
            "outcome": record.get("outcome"), "payload": payload_value,
            "requests": requests, "boundaries": boundaries}


def compare_migration(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    intent: AuditIntent,
    *,
    pair_id: str | None = None,
) -> dict[str, Any]:
    """Compare two traces under one frozen intent.

    The aggregate category uses the same mismatch-priority semantics as ``audit``.
    Per-dimension transitions are always retained because a repair in one dimension
    can coexist with an unresolved or newly failing dimension elsewhere.
    """
    before_audit = audit(before, intent)
    after_audit = audit(after, intent)
    names = sorted(set(before_audit["dimensions"]) | set(after_audit["dimensions"]))
    dimension_transitions: dict[str, Any] = {}
    for name in names:
        b = before_audit["dimensions"].get(name, {"verdict": "unknown", "reason": "not evaluated"})
        a = after_audit["dimensions"].get(name, {"verdict": "unknown", "reason": "not evaluated"})
        dimension_transitions[name] = {
            "before": b["verdict"],
            "after": a["verdict"],
            "category": _transition(b["verdict"], a["verdict"]),
            "before_reason": b.get("reason"),
            "after_reason": a.get("reason"),
        }
    before_obs = _compact_observation(before_audit)
    after_obs = _compact_observation(after_audit)
    changed_dimensions = [name for name in names if before_obs.get(name) != after_obs.get(name)]
    before_structural = _structural_summary(before)
    after_structural = _structural_summary(after)
    structural_delta = {
        key: {"before": before_structural.get(key), "after": after_structural.get(key)}
        for key in before_structural
        if before_structural.get(key) != after_structural.get(key)
    }
    return {
        "schema": 1,
        "pair_id": pair_id,
        "intent_fingerprint": intent_fingerprint(intent),
        "intent": intent.to_dict(),
        "before": before_audit,
        "after": after_audit,
        "category": _transition(before_audit["verdict"], after_audit["verdict"]),
        "dimension_transitions": dimension_transitions,
        "behavior_changed": bool(changed_dimensions),
        "changed_dimensions": changed_dimensions,
        "structural_behavior_changed": bool(structural_delta),
        "structural_delta": structural_delta,
        "before_evidence": evidence_report(before, intent),
        "after_evidence": evidence_report(after, intent),
        "interpretation": (
            "paired finite-trace conformance under one explicit intent; "
            "not automatic defect attribution and not a universal runtime guarantee"
        ),
    }
