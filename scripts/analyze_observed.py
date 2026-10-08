#!/usr/bin/env python3
"""Validate and analyze the client-witnessed RetryScope rerun.

The script treats the JSONL files as immutable measurements.  It recomputes every
trace and audit from server arrivals plus client-side witnesses, verifies the
predeclared matrix, and emits manuscript tables/figures without network access.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import statistics
import sys
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retryscope.audit import AuditIntent, audit, from_legacy
from retryscope.checker import Intent
from retryscope.observation import build_trace


def load_jsonl(paths: Iterable[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        for line_number, line in enumerate(path.read_text().splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"invalid JSON at {path}:{line_number}: {exc}") from exc
            row["_source_file"] = path.name
            rows.append(row)
    return rows


def audit_intent(config: Mapping[str, Any]) -> AuditIntent:
    values = Intent(**dict(config.get("intent", {}))).to_dict()
    values["expected_payload"] = values.pop("expected_payload_on_success")
    if values.get("time_scope") == "observation":
        values["time_scope"] = "operation"
    return AuditIntent(**values)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    position = (len(ordered) - 1) * p
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def quantiles(values: list[float]) -> dict[str, float]:
    return {
        "min": min(values),
        "q1": percentile(values, 0.25),
        "median": percentile(values, 0.50),
        "q3": percentile(values, 0.75),
        "max": max(values),
    }


def stack_label(stack: str) -> str:
    return {
        "boto": "Boto3/botocore",
        "smart_open": r"smart\_open",
        "urllib3_old": "urllib3 1.26.20",
        "urllib3_new": "urllib3 2.7.0",
        "requests_old": "Requests 2.32.3",
        "requests": "Requests 2.32.5",
        "huggingface": "Hugging Face Hub",
    }.get(stack, stack)


def validate(rows: list[dict[str, Any]], raw_dir: Path, seeds: range) -> None:
    configs = json.loads((ROOT / "study/cases.json").read_text())
    expected_ids = {config["id"] for config in configs}
    expected = {(case_id, seed) for case_id in expected_ids for seed in seeds}
    got = {(row.get("id"), row.get("seed")) for row in rows}
    if got != expected or len(rows) != len(got):
        missing = sorted(expected - got)[:12]
        extra = sorted(got - expected)[:12]
        raise SystemExit(
            f"incomplete/duplicate observed study: rows={len(rows)}, unique={len(got)}, "
            f"missing={len(expected-got)} {missing}, extra={len(got-expected)} {extra}"
        )
    for path in (raw_dir / "false.jsonl", raw_dir / "true.jsonl", raw_dir / "freeze.json"):
        if not path.exists():
            raise SystemExit(f"missing frozen input: {path}")
    for row in rows:
        case_id = row.get("id")
        if row.get("harness_error"):
            raise SystemExit(f"harness error in {case_id}/{row.get('seed')}: {row['harness_error']}")
        if row.get("trace_complete") is not True:
            raise SystemExit(f"incomplete trace in {case_id}/{row.get('seed')}")
        if row.get("cap_exceeded") is not False or not isinstance(row.get("wire_attempts"), int) or row["wire_attempts"] > 16:
            raise SystemExit(f"traffic cap failure in {case_id}/{row.get('seed')}")
        arrivals = [event for event in row.get("events", []) if event.get("kind") == "arrival"]
        if len(arrivals) != row["wire_attempts"]:
            raise SystemExit(f"arrival-count mismatch in {case_id}/{row.get('seed')}")
        rebuilt = build_trace(row)
        if rebuilt != row.get("audit_trace"):
            raise SystemExit(f"stored trace does not recompute in {case_id}/{row.get('seed')}")
        recomputed = audit(rebuilt, audit_intent(row["config"]))
        if recomputed != row.get("audit"):
            raise SystemExit(f"stored audit does not recompute in {case_id}/{row.get('seed')}")
        if rebuilt.get("retry_attribution_complete") is not True:
            raise SystemExit(f"retry attribution incomplete in {case_id}/{row.get('seed')}")
        for arrival in rebuilt.get("arrivals", [])[1:]:
            if arrival.get("role") != "retry" or not arrival.get("attribution_witness"):
                raise SystemExit(f"unattributed follow-up request in {case_id}/{row.get('seed')}")
            cause = arrival.get("cause")
            if not isinstance(cause, dict) or cause.get("kind") not in {
                "status", "body_error", "transport_error", "content_mismatch"
            }:
                raise SystemExit(f"unsupported retry cause in {case_id}/{row.get('seed')}: {cause}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, default=ROOT / "results/raw/observed")
    parser.add_argument("--out", type=Path, default=ROOT / "results/observed-derived")
    parser.add_argument("--paper-dir", type=Path)
    parser.add_argument("--seed-start", type=int, default=301)
    parser.add_argument("--seed-stop", type=int, default=313, help="exclusive")
    args = parser.parse_args()

    paths = [args.raw / "false.jsonl", args.raw / "true.jsonl"]
    rows = load_jsonl(paths)
    if not rows:
        raise SystemExit("no observed records")
    validate(rows, args.raw, range(args.seed_start, args.seed_stop))
    args.out.mkdir(parents=True, exist_ok=False)

    by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_stack: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_id[row["id"]].append(row)
        by_stack[row["config"]["stack"]].append(row)

    cell_rows: list[dict[str, Any]] = []
    for case_id, group in sorted(by_id.items()):
        elapsed_ms = [row["elapsed_s"] * 1000 for row in group]
        q = quantiles(elapsed_ms)
        audits = Counter(row["audit"]["verdict"] for row in group)
        legacy = Counter(row["legacy_check"]["verdict"] for row in group)
        classification = Counter(
            row["audit"]["dimensions"].get("classification", {}).get("verdict", "not_requested")
            for row in group
        )
        cell_rows.append({
            "id": case_id,
            "stack": group[0]["config"]["stack"],
            "scenario": group[0]["config"]["scenario"],
            "mode": group[0]["config"]["mode"],
            "n": len(group),
            "wire_min": min(row["wire_attempts"] for row in group),
            "wire_max": max(row["wire_attempts"] for row in group),
            "success": sum(row.get("outcome") == "success" for row in group),
            "audit_pass": audits["pass"],
            "audit_mismatch": audits["mismatch"],
            "audit_unknown": audits["unknown"],
            "classification_pass": classification["pass"],
            "classification_mismatch": classification["mismatch"],
            "classification_unknown": classification["unknown"],
            "legacy_pass": legacy["pass"],
            "legacy_mismatch": legacy["mismatch"],
            "legacy_unknown": legacy["unknown"],
            "median_ms": round(q["median"], 6),
            "min_ms": round(q["min"], 6),
            "max_ms": round(q["max"], 6),
        })
    write_csv(args.out / "cell-summary.csv", cell_rows)

    dimension_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        for name, result in row["audit"]["dimensions"].items():
            dimension_counts[name][result["verdict"]] += 1
    dimension_rows = [
        {
            "dimension": name,
            "requested": sum(counts.values()),
            "pass": counts["pass"],
            "mismatch": counts["mismatch"],
            "unknown": counts["unknown"],
        }
        for name, counts in sorted(dimension_counts.items())
    ]
    write_csv(args.out / "dimension-summary.csv", dimension_rows)

    stack_rows: list[dict[str, Any]] = []
    old_counterfactual: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        old_counterfactual[(row["id"], row["seed"])] = audit(from_legacy(row), audit_intent(row["config"]))
    for stack, group in sorted(by_stack.items()):
        actual = Counter(row["audit"]["verdict"] for row in group)
        legacy_evidence = Counter(old_counterfactual[(row["id"], row["seed"])]["verdict"] for row in group)
        classification = Counter(
            row["audit"]["dimensions"].get("classification", {}).get("verdict", "not_requested")
            for row in group
        )
        counterfactual_classification = Counter(
            old_counterfactual[(row["id"], row["seed"])]["dimensions"].get("classification", {}).get("verdict", "not_requested")
            for row in group
        )
        retry_arrivals = [
            arrival
            for row in group
            for arrival in row["audit_trace"]["arrivals"]
            if arrival.get("role") == "retry"
        ]
        owner_admissions = sum("retry_start" in str(arrival.get("attribution_witness")) for arrival in retry_arrivals)
        decision_results = sum("attempt_result" in str(arrival.get("attribution_witness")) for arrival in retry_arrivals)
        stack_rows.append({
            "stack": stack,
            "label": stack_label(stack),
            "records": len(group),
            "wire_requests": sum(row["wire_attempts"] for row in group),
            "retry_arrivals": len(retry_arrivals),
            "owner_admission_witnesses": owner_admissions,
            "decision_result_witnesses": decision_results,
            "audit_pass": actual["pass"],
            "audit_mismatch": actual["mismatch"],
            "audit_unknown": actual["unknown"],
            "classification_pass": classification["pass"],
            "classification_mismatch": classification["mismatch"],
            "classification_unknown": classification["unknown"],
            "server_only_aggregate_unknown": legacy_evidence["unknown"],
            "server_only_classification_unknown": counterfactual_classification["unknown"],
        })
    write_csv(args.out / "stack-evidence.csv", stack_rows)

    owner_counter: Counter[tuple[str, str, str]] = Counter()
    for row in rows:
        for arrival in row["audit_trace"]["arrivals"]:
            if arrival.get("role") != "retry":
                continue
            cause = arrival.get("cause", {})
            owner_counter[(str(arrival.get("owner")), str(cause.get("kind")), row["config"]["stack"])] += 1
    owner_rows = [
        {"owner": owner, "cause": cause, "stack": stack, "retry_arrivals": n}
        for (owner, cause, stack), n in sorted(owner_counter.items())
    ]
    write_csv(args.out / "retry-owners.csv", owner_rows)

    legacy_verdicts = Counter(row["legacy_check"]["verdict"] for row in rows)
    audit_verdicts = Counter(row["audit"]["verdict"] for row in rows)
    counterfactual_verdicts = Counter(
        old_counterfactual[(row["id"], row["seed"])]["verdict"] for row in rows
    )
    transition_counts = Counter(
        (row["legacy_check"]["verdict"], row["audit"]["verdict"]) for row in rows
    )
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    summary = {
        "schema": 1,
        "records": len(rows),
        "cells": len(by_id),
        "replicates": args.seed_stop - args.seed_start,
        "wire_requests": sum(row["wire_attempts"] for row in rows),
        "maximum_wire_requests": max(row["wire_attempts"] for row in rows),
        "client_events": sum(len(row.get("client_events", [])) for row in rows),
        "retry_arrivals": sum(
            arrival.get("role") == "retry"
            for row in rows for arrival in row["audit_trace"]["arrivals"]
        ),
        "audit_verdicts": dict(audit_verdicts),
        "baseline_checker_verdicts": dict(legacy_verdicts),
        "server_only_counterfactual_verdicts": dict(counterfactual_verdicts),
        "baseline_to_evidence_transition": {
            f"{before}_to_{after}": count for (before, after), count in sorted(transition_counts.items())
        },
        "dimension_verdicts": {
            name: dict(counts) for name, counts in sorted(dimension_counts.items())
        },
        "stacks": len(by_stack),
        "raw_sha256": hashes,
        "scope": "fresh client-witnessed rerun of the original 89-cell matrix; loopback, sequential, no production endpoint",
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    # Data-derived vector figure: supported aggregate verdicts by executed stack.
    import matplotlib
    matplotlib.use("Agg")
    matplotlib.rcParams["pdf.fonttype"] = 42
    matplotlib.rcParams["ps.fonttype"] = 42
    import matplotlib.pyplot as plt

    labels = [row["label"] for row in stack_rows]
    passes = [row["audit_pass"] for row in stack_rows]
    mismatches = [row["audit_mismatch"] for row in stack_rows]
    unknowns = [row["audit_unknown"] for row in stack_rows]
    y = list(range(len(stack_rows)))
    fig, ax = plt.subplots(figsize=(3.45, 2.65))
    ax.barh(y, passes, label="Pass")
    ax.barh(y, mismatches, left=passes, label="Mismatch")
    left2 = [p + m for p, m in zip(passes, mismatches)]
    ax.barh(y, unknowns, left=left2, label="Unknown")
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.set_xlabel("Executed operations")
    ax.grid(axis="x", alpha=0.2)
    ax.legend(ncol=3, fontsize=7, loc="lower center", bbox_to_anchor=(0.5, 1.0), frameon=False)
    fig.tight_layout()
    fig.savefig(args.out / "observed-verdicts.pdf", bbox_inches="tight")
    fig.savefig(args.out / "observed-verdicts.svg", bbox_inches="tight")
    plt.close(fig)

    # Compact manuscript data, generated rather than hand-copied.
    rows_by_stack = []
    for row in stack_rows:
        rows_by_stack.append(
            f"{row['label']} & {row['records']} & {row['retry_arrivals']} & "
            f"{row['audit_pass']} & {row['audit_mismatch']} & {row['audit_unknown']} \\\\"
        )
    (args.out / "observed-stack-rows.tex").write_text("\n".join(rows_by_stack) + "\n")
    macros = {
        "ObservedRuns": summary["records"],
        "ObservedCells": summary["cells"],
        "ObservedWires": summary["wire_requests"],
        "ObservedMaxWires": summary["maximum_wire_requests"],
        "ObservedClientEvents": summary["client_events"],
        "ObservedRetryArrivals": summary["retry_arrivals"],
        "ObservedPasses": audit_verdicts["pass"],
        "ObservedMismatches": audit_verdicts["mismatch"],
        "ObservedUnknowns": audit_verdicts["unknown"],
        "ServerOnlyUnknowns": counterfactual_verdicts["unknown"],
    }
    macro_text = "\n".join(f"\\newcommand{{\\{name}}}{{{value}}}" for name, value in macros.items()) + "\n"
    (args.out / "observed-macros.tex").write_text(macro_text)

    if args.paper_dir:
        import shutil
        generated = args.paper_dir / "generated"
        figures = args.paper_dir / "figures"
        generated.mkdir(parents=True, exist_ok=True)
        figures.mkdir(parents=True, exist_ok=True)
        for name in ("observed-stack-rows.tex", "observed-macros.tex"):
            shutil.copy2(args.out / name, generated / name)
        for name in ("observed-verdicts.pdf", "observed-verdicts.svg"):
            shutil.copy2(args.out / name, figures / name)

    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
