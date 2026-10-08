#!/usr/bin/env python3
"""Measure witness size/join cost and fail-closed behavior under evidence mutations."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from statistics import median
import time

from retryscope.causal import join_causal_trace


def percentile(values: list[int], q: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
    return float(ordered[index])


def operation_records(records):
    for cell in records:
        wire = cell["wire_events"]
        for operation in cell["operations"]:
            yield operation, wire


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    records = [json.loads(line) for line in args.raw.read_text().splitlines() if line.strip()]
    operations = list(operation_records(records))
    args.out.mkdir(parents=True, exist_ok=True)

    admission_sizes = []
    header_sizes = []
    for operation, _wire in operations:
        for event in operation["client_events"]:
            if event.get("kind") != "admission":
                continue
            admission_sizes.append(len(json.dumps(event, sort_keys=True, separators=(",", ":")).encode()))
            traceparent = f"00-{event['operation_id']}-{event['attempt_id']}-01"
            header_sizes.append(sum(len(line.encode()) for line in (
                f"traceparent: {traceparent}\r\n",
                f"x-retryscope-operation: {event['operation_id']}\r\n",
                f"x-retryscope-attempt: {event['attempt_id']}\r\n",
                f"x-retryscope-ordinal: {event['ordinal']}\r\n",
            )))

    timings = []
    sample = operations[:240]
    for repeat in range(5):
        for operation, wire in sample:
            start = time.perf_counter_ns()
            trace = join_causal_trace(
                operation["client_events"],
                wire,
                operation_id=operation["operation_id"],
                outcome=operation["outcome"],
                payload=operation["payload_digest"],
                payload_complete=operation["payload_complete"],
                elapsed_s=operation["elapsed_s"],
            )
            timings.append(time.perf_counter_ns() - start)
            if not trace["causal_join_complete"]:
                raise SystemExit("unmutated trace failed during overhead measurement")

    eligible = [item for item in operations if sum(e.get("kind") == "admission" for e in item[0]["client_events"]) >= 2][:60]
    mutation_counts = {name: 0 for name in (
        "missing_wire",
        "duplicate_wire",
        "invalid_wire_witness",
        "unknown_attempt",
        "missing_parent_admission",
        "noncausal_parent",
    )}
    detected = dict.fromkeys(mutation_counts, 0)
    for operation, shared_wire in eligible:
        op = operation["operation_id"]
        own_wire = [event for event in shared_wire if event.get("operation_id") == op]
        client = operation["client_events"]
        admissions = [event for event in client if event.get("kind") == "admission"]
        parented = [event for event in admissions if event.get("parent_attempt_id")]
        if not own_wire or not parented:
            continue
        variants = {}
        variants["missing_wire"] = (copy.deepcopy(client), copy.deepcopy(own_wire[1:]))
        reused = copy.deepcopy(own_wire[0])
        reused['global_index'] = max(event['global_index'] for event in own_wire) + 1
        reused['operation_index'] = max(event['operation_index'] for event in own_wire) + 1
        variants["duplicate_wire"] = (copy.deepcopy(client), copy.deepcopy(own_wire) + [reused])
        bad_valid = copy.deepcopy(own_wire)
        bad_valid[0]["witness_valid"] = False
        bad_valid[0]["witness_errors"] = ["mutated evidence"]
        variants["invalid_wire_witness"] = (copy.deepcopy(client), bad_valid)
        bad_attempt = copy.deepcopy(own_wire)
        bad_attempt[0]["attempt_id"] = "e" * 16 if bad_attempt[0]["attempt_id"] != "e" * 16 else "d" * 16
        variants["unknown_attempt"] = (copy.deepcopy(client), bad_attempt)
        missing_parent = copy.deepcopy(client)
        parent_id = parented[0]["parent_attempt_id"]
        missing_parent = [event for event in missing_parent if event.get("attempt_id") != parent_id]
        variants["missing_parent_admission"] = (missing_parent, copy.deepcopy(own_wire))
        noncausal = copy.deepcopy(client)
        target_id = parented[0]["attempt_id"]
        for event in noncausal:
            if event.get("attempt_id") == target_id:
                event["parent_attempt_id"] = target_id
        variants["noncausal_parent"] = (noncausal, copy.deepcopy(own_wire))
        for name, (mut_client, mut_wire) in variants.items():
            mutation_counts[name] += 1
            trace = join_causal_trace(mut_client, mut_wire, operation_id=op)
            detected[name] += int(not trace["causal_join_complete"])

    if mutation_counts != detected:
        raise SystemExit(f"mutation escaped detection: attempted={mutation_counts}, detected={detected}")
    summary = {
        "operations_sampled_for_join_timing": len(sample),
        "join_measurements": len(timings),
        "join_time_us": {
            "median": median(timings) / 1000,
            "p95": percentile(timings, 0.95) / 1000,
        },
        "witness_header_bytes_per_attempt": {
            "median": median(header_sizes),
            "minimum": min(header_sizes),
            "maximum": max(header_sizes),
        },
        "serialized_admission_bytes": {
            "median": median(admission_sizes),
            "p95": percentile(admission_sizes, 0.95),
        },
        "mutation_traces": sum(mutation_counts.values()),
        "mutation_detection": {name: {"detected": detected[name], "attempted": mutation_counts[name]} for name in mutation_counts},
    }
    (args.out / "robustness.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
