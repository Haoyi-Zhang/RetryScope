#!/usr/bin/env python3
"""Run the complete offline artifact self-check in the prepared environment."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT.parent / "paper"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_checked(command: list[str], *, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    src = str(ROOT / "src")
    env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)
    if result.returncode:
        detail = (result.stdout + "\n" + result.stderr)[-12000:]
        raise SystemExit(f"command failed ({' '.join(command)}):\n{detail}")
    return result


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def assert_same_json(actual: Path, retained: Path, *, ignore: tuple[str, ...] = ()) -> None:
    regenerated = load(actual)
    stored = load(retained)
    for key in ignore:
        regenerated.pop(key, None)
        stored.pop(key, None)
    if regenerated != stored:
        raise AssertionError(f"regenerated JSON differs: {actual.name} vs {retained}")


def run_unit_tests() -> str:
    """Use pytest's exit status; retain its current summary without a fixed count."""
    result = run_checked([sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider"])
    return result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "results/verification.json")
    args = parser.parse_args()

    checks: dict[str, Any] = {}
    # Resolve every principal declaration before any regeneration or paper writes.
    source_result = run_checked([sys.executable, "-B", str(ROOT / "scripts/verify_frozen_sources.py")])
    checks["principal_frozen_sources"] = json.loads(source_result.stdout)
    run_checked([sys.executable, str(ROOT / "scripts/verify_results.py")])
    checks["auxiliary_frozen_results"] = "passed"

    with tempfile.TemporaryDirectory(prefix="retryscope-check-") as temporary:
        temp = Path(temporary)
        outputs = {name: temp / name for name in ("observed", "extension", "async", "sync", "migration", "causal")}
        run_checked([
            sys.executable, str(ROOT / "scripts/analyze_observed.py"),
            "--raw", str(ROOT / "results/raw/observed"),
            "--out", str(outputs["observed"]),
        ])
        run_checked([
            sys.executable, str(ROOT / "scripts/analyze_extension.py"),
            "--raw", str(ROOT / "results/raw/extension"),
            "--legacy-raw", str(ROOT / "results/raw/evaluation"),
            "--out", str(outputs["extension"]),
        ])
        run_checked([
            sys.executable, str(ROOT / "scripts/analyze_async.py"),
            "--raw", str(ROOT / "results/raw/async-boundary"),
            "--out", str(outputs["async"]),
        ])
        run_checked([
            sys.executable, str(ROOT / "scripts/analyze_sync_enforcement.py"),
            "--raw", str(ROOT / "results/raw/sync-enforcement"),
            "--out", str(outputs["sync"]),
        ])
        run_checked([
            sys.executable, str(ROOT / "scripts/analyze_migrations.py"),
            "--initial-raw", str(ROOT / "results/raw/observed"),
            "--manifest", str(ROOT / "study/migration-pairs.json"),
            "--out", str(outputs["migration"]),
        ])
        run_checked([
            sys.executable, str(ROOT / "scripts/analyze_causal_witness.py"),
            "--raw", str(ROOT / "results/raw/causal-witness/records.jsonl"),
            "--out", str(outputs["causal"]),
        ])
        run_checked([
            sys.executable, str(ROOT / "scripts/analyze_causal_robustness.py"),
            "--raw", str(ROOT / "results/raw/causal-witness/records.jsonl"),
            "--out", str(outputs["causal"]),
        ])

        for name in ("observed", "async", "sync", "migration", "causal"):
            assert_same_json(outputs[name] / "summary.json", ROOT / f"results/{name}-derived/summary.json")
        assert_same_json(
            outputs["extension"] / "summary.json",
            ROOT / "results/extension-derived/summary.json",
            ignore=("offline_median_ms",),
        )
        # Robustness timing varies slightly by execution; validate invariants rather than byte identity.
        robustness = load(outputs["causal"] / "robustness.json")

    checks["principal_analysis_regeneration"] = "passed"

    run_checked([sys.executable, str(ROOT / "scripts/generate_paper.py"), "--paper-dir", str(PAPER)])
    paper_data = load(ROOT / "results/paper-data.json")
    expected_totals = {
        "configurations": 228,
        "operations": 2430,
        "wire_requests": 4986,
        "maximum_wire_requests_per_operation": 13,
    }
    assert paper_data["totals"] == expected_totals
    checks["paper_inputs"] = "passed"

    checks["tests"] = run_unit_tests()

    upstream = load(ROOT / "evidence/extension-environment.json")
    for entry in upstream["modules"]:
        assert sha256(ROOT / entry["snapshot"]) == entry["sha256"], entry["snapshot"]
    for entry in upstream["licenses"]:
        assert sha256(ROOT / entry["path"]) == entry["sha256"], entry["path"]
    for package, version in upstream["packages"].items():
        assert metadata.version(package) == version, (package, version)
    checks["installed_versions_and_snapshots"] = "passed"

    relocations = load(ROOT / "evidence/FROZEN-SOURCE-MAP.json")["relocations"]
    assert relocations
    for relocation in relocations:
        assert sha256(ROOT / relocation["preserved_path"]) == relocation["sha256"]
    checks["frozen_source_relocations"] = f"{len(relocations)} passed"

    observed = load(ROOT / "results/observed-derived/summary.json")
    extension = load(ROOT / "results/extension-derived/summary.json")
    async_summary = load(ROOT / "results/async-derived/summary.json")
    sync_summary = load(ROOT / "results/sync-derived/summary.json")
    migration = load(ROOT / "results/migration-derived/summary.json")
    causal = load(ROOT / "results/causal-derived/summary.json")

    assert observed["records"] == 1068 and observed["wire_requests"] == 1704
    assert observed["client_events"] == 1728 and observed["retry_arrivals"] == 636
    assert observed["audit_verdicts"] == {"pass": 756, "mismatch": 300, "unknown": 12}
    assert observed["dimension_verdicts"]["classification"] == {"pass": 1044, "mismatch": 12}
    assert observed["server_only_counterfactual_verdicts"] == {"mismatch": 288, "unknown": 780}

    assert extension["records"] == 402 and extension["wire_attempts"] == 858
    assert extension["content_verdicts"] == {"mismatch": 36, "pass": 366}
    assert extension["adjacent_control"] == {"n": 36, "false_alarms": 36, "attributed_false_alarms": 0}

    assert async_summary["records"] == 144 and async_summary["wire_attempts"] == 156
    assert async_summary["modes"]["inactivity"] == {"n": 48, "cleanup_pass": 24}
    assert async_summary["modes"]["admission"] == {"n": 48, "cleanup_pass": 36}
    assert async_summary["modes"]["asyncio_timeout"] == {"n": 48, "cleanup_pass": 48}

    assert sync_summary["records"] == 96 and sync_summary["wire_requests"] == 108
    assert sync_summary["modes"]["thread_future"]["cleanup_pass"] == 12
    assert sync_summary["modes"]["process_watchdog"]["cleanup_pass"] == 48

    assert migration["pair_observations"] == 96 and migration["real_pair_observations"] == 84
    assert migration["retryscope_agreement"] == [96, 96]
    assert migration["outcome_only_agreement"] == [18, 96]
    assert migration["flat_count_agreement"] == [48, 96]
    assert migration["structural_change_observations"] == 90
    assert migration["initial_source"] == "client-witnessed rerun"

    assert causal["operations"] == 720 and causal["wire_attempts"] == 2160
    assert causal["causal_joins_complete"] == 720
    assert causal["audit_verdicts"] == {"pass": 720, "mismatch": 0, "unknown": 0}
    assert causal["assignment_accuracy"]["causal_token"] == 1.0
    assert causal["edge_metrics"]["causal_token"]["f1"] == 1.0
    assert robustness["mutation_traces"] == 360
    assert all(row["detected"] == row["attempted"] == 60 for row in robustness["mutation_detection"].values())
    assert robustness["witness_header_bytes_per_attempt"] == {"median": 193, "minimum": 193, "maximum": 193}
    checks["reported_results"] = "passed"

    ledger = json.loads((ROOT / "evidence/REFERENCE-VERIFICATION.json").read_text())
    assert len(ledger) == len({entry["bibkey"] for entry in ledger}) == 68
    tex = (PAPER / "main.tex").read_text()
    bib = (PAPER / "references.bib").read_text()
    bib_keys = set(re.findall(r"^@\w+\{([^,]+)", bib, re.MULTILINE))
    cited = {
        key.strip()
        for group in re.findall(r"\\cite(?:\[[^\]]*\])?\{([^}]+)\}", tex)
        for key in group.split(",")
    }
    assert bib_keys == cited == {entry["bibkey"] for entry in ledger}
    checks["reference_closure"] = "68 verified and cited entries"

    report = {
        "schema": 1,
        "offline_self_check": "passed",
        "checks": checks,
        "principal_totals": expected_totals,
        "paired_observations": 96,
        "causal_mutations_detected": 360,
        "scope": (
            "Same prepared environment; frozen-input, deterministic-analysis, installed-version, "
            "software-test, and manuscript-input self-check. Not independent replication or peer review."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
