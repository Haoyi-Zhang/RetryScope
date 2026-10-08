import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_causal_summary_matches_delivered_raw_records():
    summary = json.loads((ROOT / "results/causal-derived/summary.json").read_text())
    assert summary["cells"] == 192
    assert summary["operations"] == 720
    assert summary["wire_attempts"] == 2160
    assert summary["causal_joins_complete"] == 720
    assert summary["audit_verdicts"] == {"pass": 720, "mismatch": 0, "unknown": 0}
    assert summary["assignment_accuracy"]["causal_token"] == 1.0
    assert summary["edge_metrics"]["causal_token"]["f1"] == 1.0


def test_causal_design_is_complete_and_unique():
    rows = [json.loads(line) for line in (ROOT / "results/raw/causal-witness/records.jsonl").read_text().splitlines() if line]
    keys = {(row["stack"], row["scenario"], row["concurrency"], row["seed"]) for row in rows}
    assert len(rows) == len(keys) == 192
    assert {row["stack"] for row in rows} == {"requests", "urllib3"}
    assert {row["scenario"] for row in rows} == {"retry", "nested", "constituent", "recovery"}
    assert {row["concurrency"] for row in rows} == {1, 2, 4, 8}
    assert all(row["score"]["joins_complete"] == row["score"]["operations"] for row in rows)


def test_timestamp_scope_stress_separates_sequential_and_concurrent_cases():
    rows = list(csv.DictReader((ROOT / "results/causal-derived/cells.csv").open()))
    sequential = [row for row in rows if row["concurrency"] == "1"]
    concurrent = [row for row in rows if row["concurrency"] in {"4", "8"}]
    assert all(float(row["timestamp_assignment"]) == 1.0 for row in sequential)
    assert max(float(row["timestamp_assignment"]) for row in concurrent) < 0.1
    assert all(float(row["token_assignment"]) == 1.0 for row in rows)


def test_all_evidence_mutations_fail_closed():
    result = json.loads((ROOT / "results/causal-derived/robustness.json").read_text())
    assert result["mutation_traces"] == 360
    assert all(row["detected"] == row["attempted"] == 60 for row in result["mutation_detection"].values())
    assert result["witness_header_bytes_per_attempt"]["median"] == 193.0
