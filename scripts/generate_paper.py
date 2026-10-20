#!/usr/bin/env python3
"""Generate manuscript totals and table rows from executed result summaries."""
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PAPER = ROOT.parent / "paper"


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def tex_row(cells: list[str]) -> str:
    return " & ".join(cells) + r" \\"


def collected_tests() -> int:
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', '--collect-only', '-q'],
        cwd=ROOT, capture_output=True, text=True, check=True, timeout=60,
    )
    match = re.search(r'(\d+) tests? collected', result.stdout)
    if match is None:
        raise RuntimeError('Could not determine the current collected test count')
    return int(match.group(1))


def validate_policy_pair_sources(observed: dict, migration: dict) -> None:
    """Reject mixing policy observations with pairs derived from another collection."""
    policy = observed.get('raw_sha256', {})
    paired = migration.get('initial_raw_sha256', {})
    required = {'false.jsonl', 'true.jsonl'}
    if not required.issubset(policy) or not required.issubset(paired):
        raise ValueError('Policy and migration summaries must identify both raw policy inputs.')
    if any(policy[name] != paired[name] for name in required):
        raise ValueError('Policy and migration pairs refer to different raw observations.')
    mode = observed.get('analysis_mode', 'historical')
    if mode not in ('current', 'historical'):
        raise ValueError('Unsupported policy analysis mode.')
    collection = migration.get('phase_sources', {}).get('initial', {}).get('collection')
    expected = 'current' if mode == 'current' else 'retained'
    if collection != expected:
        raise ValueError('Policy analysis mode and migration initial collection disagree.')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-dir", type=Path, default=DEFAULT_PAPER)
    parser.add_argument("--observed-derived", type=Path,
                        help="explicitly select the validated policy matrix used by the manuscript")
    parser.add_argument("--migration-derived", type=Path,
                        help="explicitly select the paired analysis and its phase-source accounting")
    parser.add_argument('--check-only', action='store_true',
                        help='validate selected result sources and scientific totals without writing manuscript inputs')
    args = parser.parse_args()

    observed_dir = args.observed_derived or ROOT / "results/native-policy-derived"
    observed = load(observed_dir / "summary.json")
    extension = load(ROOT / "results/extension-derived/summary.json")
    async_summary = load(ROOT / "results/async-derived/summary.json")
    sync_summary = load(ROOT / "results/sync-derived/summary.json")
    migration_dir = args.migration_derived or ROOT / "results/migration-derived"
    migration = load(migration_dir / "summary.json")
    validate_policy_pair_sources(observed, migration)
    causal = load(ROOT / "results/causal-derived/summary.json")
    with (ROOT / "results/causal-derived/cells.csv").open(newline="") as handle:
        causal_configurations = len(list(csv.DictReader(handle)))
    assert causal_configurations == 32

    phases = [
        ("Policy, HTTP, and integration", observed["cells"], observed["records"], observed["wire_requests"]),
        ("Identity, range, and constituents", extension["cells"], extension["records"], extension["wire_attempts"]),
        ("Asynchronous boundaries", async_summary["cells"], async_summary["records"], async_summary["wire_attempts"]),
        ("Synchronous enforcement boundaries", sync_summary["cells"], sync_summary["records"], sync_summary["wire_requests"]),
        ("Concurrent causal attribution", causal_configurations, causal["operations"], causal["wire_attempts"]),
    ]
    total_cells = sum(row[1] for row in phases)
    total_ops = sum(row[2] for row in phases)
    total_wires = sum(row[3] for row in phases)
    max_wires = max(
        observed["maximum_wire_requests"],
        extension["max_wire_attempts"],
        async_summary["max_wire_attempts"],
        sync_summary["max_wire_requests"],
        4,
    )

    assert (total_cells, total_ops, total_wires, max_wires) == (228, 2430, 4986, 13)
    assert sum(observed["audit_verdicts"].values()) == observed["records"]
    assert sum(observed["server_only_counterfactual_verdicts"].values()) == observed["records"]
    if observed.get("analysis_mode", "historical") == "historical":
        assert observed["audit_verdicts"] == {"pass": 756, "mismatch": 300, "unknown": 12}
        assert observed["server_only_counterfactual_verdicts"] == {"mismatch": 288, "unknown": 780}
    else:
        assert observed["analysis_mode"] == "current"
        assert observed["source_provenance"]["analysis_mode"] == "current"
    assert causal["causal_joins_complete"] == causal["operations"] == 720
    assert causal["assignment_accuracy"]["causal_token"] == 1.0
    assert causal["edge_metrics"]["causal_token"]["f1"] == 1.0
    if observed.get('analysis_mode', 'historical') == 'current':
        assert migration["initial_source"] == "client-witnessed rerun"

    if args.check_only:
        print(json.dumps({'policy_matrix': str(observed_dir),
                          'migration_pairs': str(migration_dir),
                          'raw_policy_inputs_match': True,
                          'totals': [total_cells, total_ops, total_wires, max_wires],
                          'manuscript_files_written': 0}))
        return

    generated = args.paper_dir / "generated"
    figures = args.paper_dir / "figures"
    generated.mkdir(parents=True, exist_ok=True)
    figures.mkdir(parents=True, exist_ok=True)

    macros = [
        rf"\newcommand{{\TotalRuns}}{{{total_ops:,}}}",
        rf"\newcommand{{\TotalCells}}{{{total_cells}}}",
        rf"\newcommand{{\TotalWires}}{{{total_wires:,}}}",
        rf"\newcommand{{\TotalMaxWires}}{{{max_wires}}}",
        r"\newcommand{\ReferenceCount}{68}",
        rf"\newcommand{{\TestCount}}{{{collected_tests()}}}",
    ]
    (generated / "study-macros.tex").write_text("\n".join(macros) + "\n")

    rows = [tex_row([name, f"{cells:,}", f"{ops:,}", f"{wires:,}"]) for name, cells, ops, wires in phases]
    rows.append(tex_row([r"\textbf{Total}", rf"\textbf{{{total_cells:,}}}", rf"\textbf{{{total_ops:,}}}", rf"\textbf{{{total_wires:,}}}"]))
    (generated / "evaluation-rows.tex").write_text("\n".join(rows) + "\n")

    dim_order = ["attempts", "classification", "outcome", "payload", "time"]
    dim_rows = []
    for dim in dim_order:
        counts = observed["dimension_verdicts"][dim]
        requested = sum(counts.values())
        dim_rows.append(tex_row([dim.capitalize(), f"{requested:,}", f"{counts.get('pass', 0):,}", f"{counts.get('mismatch', 0):,}", f"{counts.get('unknown', 0):,}"]))
    (generated / "observed-dimension-rows.tex").write_text("\n".join(dim_rows) + "\n")

    with (observed_dir / "cell-summary.csv").open(newline="") as handle:
        cell_by_id = {row["id"]: row for row in csv.DictReader(handle)}
    boto_specs = [
        ("Pre-policy default", "boto_false_default"),
        ("2026 default", "boto_true_default"),
        ("Pre-policy explicit standard", "boto_false_explicit_standard"),
        ("2026 explicit standard", "boto_true_explicit_standard"),
        ("2026 two-retry limit", "boto_true_max2"),
        ("2026 two-total-attempt limit", "boto_true_total2"),
    ]
    boto_rows = []
    for label, case_id in boto_specs:
        row = cell_by_id[case_id]
        assert row["wire_min"] == row["wire_max"]
        boto_rows.append(tex_row([label, row["wire_min"], f"{float(row['median_ms']):.1f}", f"[{float(row['min_ms']):.1f}, {float(row['max_ms']):.1f}] "]))
    (generated / "boto-rows.tex").write_text("\n".join(boto_rows) + "\n")

    # Copy all remaining manuscript inputs from the retained, verified derived results.
    generated_inputs = {
        observed_dir / "observed-macros.tex": generated / "observed-macros.tex",
        observed_dir / "observed-stack-rows.tex": generated / "observed-stack-rows.tex",
        ROOT / "results/extension-derived/download-rows.tex": generated / "download-rows.tex",
        migration_dir / "migration-macros.tex": generated / "migration-macros.tex",
        migration_dir / "migration-category-rows.tex": generated / "migration-category-rows.tex",
        migration_dir / "migration-rows.tex": generated / "migration-rows.tex",
        ROOT / "results/sync-derived/sync-macros.tex": generated / "sync-macros.tex",
        ROOT / "results/sync-derived/sync-rows.tex": generated / "sync-rows.tex",
        ROOT / "results/causal-derived/causal-macros.tex": generated / "causal-macros.tex",
        ROOT / "results/causal-derived/causal-rows.tex": generated / "causal-rows.tex",
    }
    figure_inputs = {
        ROOT / "results/extension-derived/constituent-count.pdf": figures / "constituent-count.pdf",
        ROOT / "results/extension-derived/constituent-count.svg": figures / "constituent-count.svg",
        ROOT / "results/sync-derived/sync-cleanup.pdf": figures / "sync-cleanup.pdf",
        ROOT / "results/sync-derived/sync-cleanup.svg": figures / "sync-cleanup.svg",
        ROOT / "results/causal-derived/causal-attribution.pdf": figures / "causal-attribution.pdf",
        ROOT / "results/causal-derived/causal-attribution.svg": figures / "causal-attribution.svg",
    }
    for source, destination in {**generated_inputs, **figure_inputs}.items():
        if not source.is_file():
            raise FileNotFoundError(f"missing generated manuscript input: {source}")
        shutil.copy2(source, destination)

    report = {
        "policy_matrix": observed_dir.relative_to(ROOT).as_posix() if observed_dir.is_relative_to(ROOT) else observed_dir.as_posix(),
        "policy_analysis_mode": observed.get("analysis_mode", "historical"),
        "migration_pairs_use_retained_policy_records": migration.get("phase_sources", {}).get("initial", {}).get("collection", "retained") == "retained",
        "migration_phase_sources": migration.get("phase_sources", {}),
        "phases": [
            {"name": name, "configurations": cells, "operations": ops, "wire_requests": wires}
            for name, cells, ops, wires in phases
        ],
        "totals": {
            "configurations": total_cells,
            "operations": total_ops,
            "wire_requests": total_wires,
            "maximum_wire_requests_per_operation": max_wires,
        },
        "paired_migration_reuses_operations": migration["pair_observations"],
        "causal_seeded_batches": causal["cells"],
    }
    (ROOT / "results/paper-data.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
