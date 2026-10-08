#!/usr/bin/env python3
"""Validate and summarize the synchronous enforcement-boundary extension."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import statistics
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from retryscope.audit import AuditIntent, audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, default=ROOT / "results/raw/sync-enforcement")
    parser.add_argument("--out", type=Path, default=ROOT / "results/sync-derived")
    parser.add_argument("--paper-dir", type=Path)
    args = parser.parse_args()
    freeze = json.loads((args.raw / "freeze.json").read_text())
    frozen_relocations = {
        "src/retryscope/audit.py": ROOT / "evidence/source-snapshots/frozen-sequential-audit.py",
        "study/sync-enforcement-protocol.md": ROOT / "evidence/source-snapshots/frozen-sync-protocol.md",
    }
    for relative, digest in freeze["sources"].items():
        path = ROOT / relative
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest and relative in frozen_relocations:
            path = frozen_relocations[relative]
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise SystemExit(f"frozen source changed: {relative}")
    rows = [json.loads(line) for line in (args.raw / "records.jsonl").read_text().splitlines() if line.strip()]
    expected = {(case["id"], seed) for case in freeze["cases"] for seed in freeze["seeds"]}
    got = {(row["id"], row["seed"]) for row in rows}
    if len(rows) != len(got) or got != expected:
        raise SystemExit(f"incomplete/duplicate sync study: rows={len(rows)} missing={len(expected-got)}")
    for row in rows:
        if row["cap_exceeded"] or not row["server_quiesced"] or not row["cleanup_complete"] or row["worker_alive_after"]:
            raise SystemExit(f"cleanup/cap failure: {row['id']}/{row['seed']}")
        if not 1 <= row["wire_attempts"] <= 16 or row["wire_attempts"] != len(row["arrivals"]):
            raise SystemExit(f"wire count failure: {row['id']}/{row['seed']}")
        expected_audit = audit(
            row,
            AuditIntent(
                budget_s=row["budget_s"], tolerance_s=0.04, boundary="cleanup",
                provenance="explicit local synchronous operation cleanup boundary",
            ),
        )
        if expected_audit != row["cleanup_audit"]:
            raise SystemExit(f"audit mismatch: {row['id']}/{row['seed']}")
        if row["mechanism_outcome"] != row["expected_mechanism_outcome"]:
            raise SystemExit(f"unexpected mechanism outcome: {row['id']}/{row['seed']}")
        if row["case"]["scenario"] == "success" and row.get("worker_outcome") != "success":
            raise SystemExit(f"healthy operation not preserved: {row['id']}/{row['seed']}")

    args.out.mkdir(parents=True, exist_ok=False)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["id"]].append(row)
    cell_rows: list[dict[str, Any]] = []
    for case in freeze["cases"]:
        subset = grouped[case["id"]]
        elapsed = [1000 * row["cleanup_elapsed_s"] for row in subset]
        setup = [1000 * row["setup_s"] for row in subset]
        cell_rows.append({
            **case,
            "n": len(subset),
            "budget_ms": 1000 * subset[0]["budget_s"],
            "cleanup_pass": sum(row["cleanup_audit"]["verdict"] == "pass" for row in subset),
            "timeout_signals": sum(row["timeout_signalled"] for row in subset),
            "healthy_success": sum(row.get("worker_outcome") == "success" for row in subset),
            "wire_min": min(row["wire_attempts"] for row in subset),
            "wire_max": max(row["wire_attempts"] for row in subset),
            "median_cleanup_ms": statistics.median(elapsed),
            "min_cleanup_ms": min(elapsed),
            "max_cleanup_ms": max(elapsed),
            "median_setup_ms": statistics.median(setup),
        })
    with (args.out / "cells.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(cell_rows[0]))
        writer.writeheader(); writer.writerows(cell_rows)

    summary = {
        "records": len(rows),
        "cells": len(freeze["cases"]),
        "seeds": freeze["seeds"],
        "wire_requests": sum(row["wire_attempts"] for row in rows),
        "max_wire_requests": max(row["wire_attempts"] for row in rows),
        "cleanup_verdicts": dict(Counter(row["cleanup_audit"]["verdict"] for row in rows)),
        "mechanism_outcomes": dict(Counter(row["mechanism_outcome"] for row in rows)),
        "modes": {},
        "raw_sha256": hashlib.sha256((args.raw / "records.jsonl").read_bytes()).hexdigest(),
        "scope": "pre-initialized local synchronous Requests operation; thread signal versus spawned-process termination",
    }
    for mode in ("thread_future", "process_watchdog"):
        subset = [row for row in rows if row["case"]["mode"] == mode]
        summary["modes"][mode] = {
            "records": len(subset),
            "cleanup_pass": sum(row["cleanup_audit"]["verdict"] == "pass" for row in subset),
            "healthy_success": sum(row["case"]["scenario"] == "success" and row.get("worker_outcome") == "success" for row in subset),
            "expected_timeouts": sum(row["case"]["scenario"] != "success" for row in subset),
            "timeout_signals": sum(row["timeout_signalled"] for row in subset),
            "median_setup_ms": statistics.median(1000 * row["setup_s"] for row in subset),
        }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    by_key = {(row["mode"], row["scenario"], row["scale"]): row for row in cell_rows}
    lines: list[str] = []
    for mode, label in (("thread_future", "Thread future"), ("process_watchdog", "Process boundary")):
        for scale in (1.0, 1.5):
            parts = []
            for scenario in ("success", "trickle", "slow_headers", "retry_delay"):
                row = by_key[(mode, scenario, scale)]
                parts.append(f"{row['median_cleanup_ms']:.1f} [{row['min_cleanup_ms']:.1f}, {row['max_cleanup_ms']:.1f}]")
            lines.append(f"{label} & {250*scale:.0f} & " + " & ".join(parts) + r" \\")
    (args.out / "sync-rows.tex").write_text("\n".join(lines) + "\n")

    import matplotlib
    matplotlib.use("Agg")
    matplotlib.rcParams["pdf.fonttype"] = 42
    matplotlib.rcParams["ps.fonttype"] = 42
    matplotlib.rcParams['font.family'] = 'serif'
    matplotlib.rcParams['font.serif'] = ['Times New Roman', 'Nimbus Roman', 'Liberation Serif', 'DejaVu Serif']
    import matplotlib.pyplot as plt

    labels = ["Healthy", "Progressing body", "Delayed headers", "Retry delay"]
    x = list(range(4))
    fig, ax = plt.subplots(figsize=(3.48, 2.45))
    for mode, label, marker in (("thread_future", "Thread future", "o"), ("process_watchdog", "Process boundary", "s")):
        medians = [by_key[(mode, scenario, 1.0)]["median_cleanup_ms"] for scenario in ("success", "trickle", "slow_headers", "retry_delay")]
        mins = [by_key[(mode, scenario, 1.0)]["min_cleanup_ms"] for scenario in ("success", "trickle", "slow_headers", "retry_delay")]
        maxs = [by_key[(mode, scenario, 1.0)]["max_cleanup_ms"] for scenario in ("success", "trickle", "slow_headers", "retry_delay")]
        ax.errorbar(x, medians, yerr=[[m-n for m,n in zip(medians, mins)], [n-m for m,n in zip(medians, maxs)]], marker=marker, capsize=3, label=label)
    ax.axhline(290, linestyle="--", linewidth=1, label="250 ms + tolerance")
    ax.set_xticks(x, labels, rotation=18, ha="right")
    ax.set_ylabel("Through cleanup (ms)")
    ax.grid(axis="y", alpha=0.2)
    ax.legend(frameon=False, fontsize=7, ncol=3, loc="lower center", bbox_to_anchor=(0.5, 1.0))
    fig.tight_layout()
    fig.savefig(args.out / "sync-cleanup.pdf", bbox_inches="tight")
    fig.savefig(args.out / "sync-cleanup.svg", bbox_inches="tight")
    plt.close(fig)

    macros = {
        "SyncRuns": summary["records"],
        "SyncCells": summary["cells"],
        "SyncWires": summary["wire_requests"],
        "ThreadCleanupPass": summary["modes"]["thread_future"]["cleanup_pass"],
        "ProcessCleanupPass": summary["modes"]["process_watchdog"]["cleanup_pass"],
    }
    (args.out / "sync-macros.tex").write_text(
        "\n".join(f"\\newcommand{{\\{key}}}{{{value}}}" for key, value in macros.items()) + "\n"
    )
    if args.paper_dir:
        import shutil
        (args.paper_dir / "generated").mkdir(parents=True, exist_ok=True)
        (args.paper_dir / "figures").mkdir(parents=True, exist_ok=True)
        for name in ("sync-rows.tex", "sync-macros.tex"):
            shutil.copy2(args.out / name, args.paper_dir / "generated" / name)
        for name in ("sync-cleanup.pdf", "sync-cleanup.svg"):
            shutil.copy2(args.out / name, args.paper_dir / "figures" / name)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
