#!/usr/bin/env python3
"""Aggregate causal-witness study records and generate paper inputs."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from statistics import median
from typing import Any

from causal_witness_study import OperationResult, _score_batch


def weighted(rows: list[dict[str, Any]], group: str, metric: str) -> float:
    total = sum(row["score"]["wire_attempts"] for row in rows)
    return sum(row["score"][group][metric] * row["score"]["wire_attempts"] for row in rows) / total


def edge_aggregate(rows: list[dict[str, Any]], method: str) -> dict[str, float | int]:
    predicted = sum(row["score"]["edge_metrics"][method]["predicted"] for row in rows)
    expected = sum(row["score"]["edge_metrics"][method]["expected"] for row in rows)
    true_positive = sum(row["score"]["edge_metrics"][method]["true_positive"] for row in rows)
    precision = true_positive / predicted if predicted else (1.0 if not expected else 0.0)
    recall = true_positive / expected if expected else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "predicted": predicted,
        "expected": expected,
        "true_positive": true_positive,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    records = [json.loads(line) for line in args.raw.read_text().splitlines() if line.strip()]
    for row in records:
        operations = [OperationResult(**{'error': None, **operation}) for operation in row['operations']]
        row['score'] = _score_batch(operations, row['wire_events'], row['scenario'])
    args.out.mkdir(parents=True, exist_ok=True)
    if len(records) != 192:
        raise SystemExit(f"expected 192 cells, observed {len(records)}")
    keys = {(row["stack"], row["scenario"], row["concurrency"], row["seed"]) for row in records}
    if len(keys) != 192:
        raise SystemExit("duplicate or missing study cell")
    operations = sum(row["score"]["operations"] for row in records)
    wire_attempts = sum(row["score"]["wire_attempts"] for row in records)
    joins_complete = sum(row["score"]["joins_complete"] for row in records)
    audit_counts = {name: sum(row["score"]["audit_verdicts"].get(name, 0) for row in records) for name in ("pass", "mismatch", "unknown")}
    summary = {
        "cells": len(records),
        "operations": operations,
        "wire_attempts": wire_attempts,
        "causal_joins_complete": joins_complete,
        "audit_verdicts": audit_counts,
        "assignment_accuracy": {
            "causal_token": weighted(records, "assignment_accuracy", "causal_token"),
            "timestamp_window": weighted(records, "assignment_accuracy", "timestamp_window"),
        },
        "role_accuracy": {
            "causal_token": weighted(records, "role_accuracy", "causal_token"),
            "timestamp_window": weighted(records, "role_accuracy", "timestamp_window"),
            "adjacency": weighted(records, "role_accuracy", "adjacency"),
        },
        "owner_accuracy": {
            "causal_token": weighted(records, "owner_accuracy", "causal_token"),
            "timestamp_window": weighted(records, "owner_accuracy", "timestamp_window"),
        },
        "edge_metrics": {
            "causal_token": edge_aggregate(records, "causal_token"),
            "timestamp_window": edge_aggregate(records, "timestamp_window"),
        },
    }
    elapsed = [operation["elapsed_s"] for row in records for operation in row["operations"]]
    summary["elapsed_ms"] = {
        "median": median(elapsed) * 1000,
        "maximum": max(elapsed) * 1000,
    }
    if summary["causal_joins_complete"] != operations or summary["audit_verdicts"] != {"pass": operations, "mismatch": 0, "unknown": 0}:
        raise SystemExit("causal join or audit completeness regression")
    if summary["assignment_accuracy"]["causal_token"] != 1.0 or summary["edge_metrics"]["causal_token"]["f1"] != 1.0:
        raise SystemExit("causal token oracle mismatch")
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    groups: list[dict[str, Any]] = []
    for stack in sorted({row["stack"] for row in records}):
        for scenario in sorted({row["scenario"] for row in records}):
            for concurrency in sorted({row["concurrency"] for row in records}):
                rows = [row for row in records if row["stack"] == stack and row["scenario"] == scenario and row["concurrency"] == concurrency]
                groups.append({
                    "stack": stack,
                    "scenario": scenario,
                    "concurrency": concurrency,
                    "operations": sum(row["score"]["operations"] for row in rows),
                    "wire_attempts": sum(row["score"]["wire_attempts"] for row in rows),
                    "token_assignment": weighted(rows, "assignment_accuracy", "causal_token"),
                    "timestamp_assignment": weighted(rows, "assignment_accuracy", "timestamp_window"),
                    "token_role": weighted(rows, "role_accuracy", "causal_token"),
                    "timestamp_role": weighted(rows, "role_accuracy", "timestamp_window"),
                    "adjacency_role": weighted(rows, "role_accuracy", "adjacency"),
                    "token_edge_f1": edge_aggregate(rows, "causal_token")["f1"],
                    "timestamp_edge_f1": edge_aggregate(rows, "timestamp_window")["f1"],
                })
    with (args.out / "cells.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(groups[0]))
        writer.writeheader()
        writer.writerows(groups)

    rows_tex = []
    for method, label in (("causal_token", "Causal token"), ("timestamp_window", "Time window")):
        rows_tex.append(
            f"{label} & {summary['assignment_accuracy'][method]*100:.1f} & "
            f"{summary['role_accuracy'][method]*100:.1f} & {summary['owner_accuracy'][method]*100:.1f} & "
            f"{summary['edge_metrics'][method]['f1']*100:.1f} \\\\"
        )
    rows_tex.append(
        f"Adjacency rule & -- & {summary['role_accuracy']['adjacency']*100:.1f} & -- & -- \\\\"
    )
    (args.out / "causal-rows.tex").write_text("\n".join(rows_tex) + "\n")
    (args.out / "causal-macros.tex").write_text(
        "\n".join([
            f"\\newcommand{{\\CausalCells}}{{{summary['cells']}}}",
            f"\\newcommand{{\\CausalOperations}}{{{summary['operations']:,}}}",
            f"\\newcommand{{\\CausalWires}}{{{summary['wire_attempts']:,}}}",
            f"\\newcommand{{\\CausalTokenAccuracy}}{{{summary['assignment_accuracy']['causal_token']*100:.1f}\\%}}",
            f"\\newcommand{{\\CausalTimestampAccuracy}}{{{summary['assignment_accuracy']['timestamp_window']*100:.1f}\\%}}",
            f"\\newcommand{{\\CausalAdjacencyRoleAccuracy}}{{{summary['role_accuracy']['adjacency']*100:.1f}\\%}}",
            f"\\newcommand{{\\CausalTimestampEdgeFOne}}{{{summary['edge_metrics']['timestamp_window']['f1']*100:.1f}\\%}}",
        ]) + "\n"
    )


if __name__ == "__main__":
    main()
