#!/usr/bin/env python3
"""Read-only OFFLINE check of P114's adopted current selection, NOT all history.

Run with --root ARTIFACT; optionally --paper-dir PAPER checks published count
macros too. No collectors, analyzer mains, plots, benchmarks or generators run.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
import csv
from datetime import datetime
import importlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
RETAINED = {
    "extension": ("scripts/extend_study.py", "src/retryscope/audit.py",
                  "src/retryscope/range_fixture.py", "study/extension-protocol.md"),
    "async-boundary": ("scripts/async_boundary_study.py", "src/retryscope/audit.py",
                       "src/retryscope/responder.py", "study/async-boundary-protocol.md"),
    "sync-enforcement": ("scripts/sync_enforcement_study.py", "src/retryscope/audit.py",
                         "src/retryscope/responder.py", "study/sync-enforcement-protocol.md"),
}
PHASE_SOURCES = {
    "initial": {"pair_observations": 54, "collection": "current"},
    "extension": {"pair_observations": 30, "collection": "retained"},
    "async": {"pair_observations": 12, "collection": "retained"},
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def same(actual, expected, label):
    # JSON canonicalization distinguishes bool/int and float/int, including -O.
    require(json.dumps(actual, sort_keys=True, allow_nan=False) ==
            json.dumps(expected, sort_keys=True, allow_nan=False), f"{label} differs")


def parse(text, label):
    def object_pairs(pairs):
        obj = {}
        for key, value in pairs:
            require(key not in obj, f"duplicate JSON key in {label}: {key}")
            obj[key] = value
        return obj
    def bad_constant(value):
        raise ValueError(f"nonfinite JSON in {label}: {value}")
    return json.loads(text, object_pairs_hook=object_pairs,
                      parse_constant=bad_constant)


def load(path):
    return parse(path.read_text(encoding="utf-8"), path)


def jsonl(path):
    # Share the strict JSON loader without creating any temporary input files.
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            rows.append(parse(line, f"{path}:{number}"))
    return rows


def inside(root, relative):
    require(isinstance(relative, str) and bool(relative), "missing relative path")
    path = (root / relative).resolve()
    require(not Path(relative).is_absolute() and path.is_relative_to(root.resolve()),
            f"path outside selected artifact: {relative}")
    return path


@contextmanager
def helpers(root):
    """Import only the selected artifact's helpers; restore caller module state."""
    names = ("analyze_observed", "analyze_migrations", "run_observed_current",
             "verify_frozen_sources")
    def owned(name):
        return (name in names or name == "retryscope" or name.startswith("retryscope.")
                or name.startswith("_retryscope_retained_"))
    saved = {k: v for k, v in sys.modules.items() if owned(k)}
    old_path, old_bytecode = sys.path[:], sys.dont_write_bytecode
    try:
        for name in saved:
            del sys.modules[name]
        sys.dont_write_bytecode = True
        sys.path[:0] = [str(root / "scripts"), str(root / "src")]
        modules = [importlib.import_module(name) for name in names]
        for name, module in zip(names, modules):
            same(Path(module.__file__).resolve().as_posix(),
                 (root / "scripts" / f"{name}.py").resolve().as_posix(),
                 f"selected helper {name}")
        yield modules
    finally:
        for name in list(sys.modules):
            if owned(name):
                del sys.modules[name]
        sys.modules.update(saved)
        sys.path[:] = old_path
        sys.dont_write_bytecode = old_bytecode


def retained_sources(root, resolver):
    mapping = load(root / "evidence/FROZEN-SOURCE-MAP.json")
    same(sorted(mapping), ["relocations", "schema"], "source-map fields")
    same(mapping["schema"], 1, "source-map schema")
    declarations = {}
    for phase, paths in RETAINED.items():
        freeze = load(root / f"results/raw/{phase}/freeze.json")
        require("files" not in freeze, f"ambiguous declarations for {phase}")
        same(sorted(freeze["sources"]), sorted(paths), f"{phase} declaration set")
        for relative, digest in freeze["sources"].items():
            inside(root, relative)
            require(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
                    f"invalid {phase} source digest")
        declarations[phase] = freeze["sources"]
    seen = set()
    for row in mapping["relocations"]:
        same(sorted(row), ["frozen_path", "preserved_path", "reason", "sha256"],
             "relocation fields")
        inside(root, row["frozen_path"])
        preserved = inside(root, row["preserved_path"])
        require(re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is not None,
                "invalid relocation digest")
        require(isinstance(row["reason"], str) and bool(row["reason"].strip()), "missing relocation reason")
        key = (row["frozen_path"], row["sha256"])
        require(key not in seen, "ambiguous duplicate relocation")
        seen.add(key)
        if any(values.get(key[0]) == key[1] for values in declarations.values()):
            same(resolver.sha256(preserved), key[1], f"retained relocation {key[0]}")
    # A fresh imported resolver is scoped in memory, never the old verifier/CLI.
    resolver.PRINCIPAL_PHASES = tuple(RETAINED)
    report = resolver.resolve_frozen_sources(root)
    require(not report["unresolved"],
            "selected retained source hold: " + json.dumps(report["unresolved"]))
    same(report["declared_entries"], sum(map(len, declarations.values())),
         "retained source coverage")
    return report


def policy(root, observed, resolver):
    raw = root / "results/raw/native-policy"
    freeze = load(raw / "freeze.json")
    same(sorted(freeze), ["analysis_mode", "files", "ids", "phase", "seeds", "utc"],
         "current freeze fields")
    same(freeze["phase"], "observed-current", "current phase")
    same(freeze["ids"], "", "complete current matrix selection")
    offset = datetime.fromisoformat(freeze["utc"]).utcoffset()
    require(offset is not None and offset.total_seconds() == 0,
            "current freeze requires timezone-marked UTC")
    seeds = [int(value) for value in freeze["seeds"].split(",")]
    same(seeds, list(range(301, 313)), "adopted current seeds")
    configs = load(root / "study/cases.json")
    by_id = {c["id"]: c for c in configs}
    same(len(by_id), len(configs), "unique policy cases")
    rows = []
    for flag in ("false", "true"):
        for row in jsonl(raw / f"{flag}.jsonl"):
            require(type(row["seed"]) is int and type(row["wire_attempts"]) is int,
                    "policy seed/wire type")
            same(row["config"], by_id[row["id"]], "policy case binding")
            same(row["phase"], freeze["phase"], "policy row phase")
            same(row["config"].get("flag", "true"), flag, "policy file binding")
            if row["config"]["stack"] in {"boto", "smart_open"} or "requested_flag" in row:
                same(row["requested_flag"], flag, "policy requested flag")
            row.update(_source_file=f"{flag}.jsonl", _file=flag, _observed_initial=True)
            rows.append(row)
    provenance = observed.validate(rows, raw, seeds, analysis_mode="current",
                                   source_snapshot=raw / "source-snapshot")
    checker = importlib.import_module("retryscope.checker")
    for row in rows:
        same(row["legacy_check"], checker.check(row, checker.Intent(**row["config"].get("intent", {}))),
             "policy baseline audit")
    dimensions = defaultdict(Counter)
    for row in rows:
        for name, result in row["audit"]["dimensions"].items():
            dimensions[name][result["verdict"]] += 1
    transitions = Counter((r["legacy_check"]["verdict"], r["audit"]["verdict"]) for r in rows)
    summary = {
        "schema": 1, "records": len(rows), "cells": len(by_id), "replicates": len(seeds),
        "wire_requests": sum(r["wire_attempts"] for r in rows),
        "maximum_wire_requests": max(r["wire_attempts"] for r in rows),
        "client_events": sum(len(r.get("client_events", [])) for r in rows),
        "retry_arrivals": sum(a.get("role") == "retry" for r in rows for a in r["audit_trace"]["arrivals"]),
        "audit_verdicts": dict(Counter(r["audit"]["verdict"] for r in rows)),
        "baseline_checker_verdicts": dict(Counter(r["legacy_check"]["verdict"] for r in rows)),
        "server_only_counterfactual_verdicts": dict(Counter(
            observed.audit(observed.from_legacy(r), observed.audit_intent(r["config"]))["verdict"] for r in rows)),
        "baseline_to_evidence_transition": {f"{a}_to_{b}": n for (a, b), n in sorted(transitions.items())},
        "dimension_verdicts": {k: dict(v) for k, v in sorted(dimensions.items())},
        "stacks": len({r["config"]["stack"] for r in rows}),
        "raw_sha256": {f"{flag}.jsonl": resolver.sha256(raw / f"{flag}.jsonl") for flag in ("false", "true")},
        "scope": "fresh client-witnessed rerun of the original 89-cell matrix; loopback, sequential, no production endpoint",
        "analysis_mode": "current", "source_provenance": provenance,
    }
    same([summary[k] for k in ("cells", "records", "wire_requests")], [89, 1068, 1704],
         "adopted current matrix")
    same(load(root / "results/native-policy-derived/summary.json"), summary, "native policy summary")
    return rows, summary


def retained_counts(root, resolver):
    counts, sources, inputs = [], {}, {}
    for phase, derived, label, wire, maximum in (
        ("extension", "extension", "Identity, range, and constituents", "wire_attempts", "max_wire_attempts"),
        ("async-boundary", "async", "Asynchronous boundaries", "wire_attempts", "max_wire_attempts"),
        ("sync-enforcement", "sync", "Synchronous enforcement boundaries", "wire_requests", "max_wire_requests"),
    ):
        raw = root / f"results/raw/{phase}"
        freeze, rows = load(raw / "freeze.json"), jsonl(raw / "records.jsonl")
        cases = {c["id"]: c for c in freeze["cases"]}
        require(len(cases) == len(freeze["cases"]) and bool(cases), f"{phase} duplicate/empty cases")
        seeds = freeze["seeds"]
        require(bool(seeds) and all(type(s) is int for s in seeds) and len(set(seeds)) == len(seeds),
                f"{phase} seed declaration")
        expected = {(c, s) for c in cases for s in seeds}
        got = {(r["id"], r["seed"]) for r in rows}
        require(got == expected and len(rows) == len(got), f"{phase} incomplete/duplicate matrix")
        for row in rows:
            same(row["case"], cases[row["id"]], f"{phase} case binding")
            require(type(row["seed"]) is int and type(row["wire_attempts"]) is int
                    and 1 <= row["wire_attempts"] <= 16, f"{phase} seed/wire type or cap")
            same(row["wire_attempts"], len(row["arrivals"]), f"{phase} arrival count")
            same(row["wire_attempts"], sum(e["kind"] == "arrival" for e in row["events"]),
                 f"{phase} event count")
        summary = load(root / f"results/{derived}-derived/summary.json")
        values = {"records": len(rows), "cells": len(cases), wire: sum(r["wire_attempts"] for r in rows),
                  maximum: max(r["wire_attempts"] for r in rows),
                  "raw_sha256": resolver.sha256(raw / "records.jsonl")}
        for key, value in values.items():
            same(summary[key], value, f"{phase} {key}")
        counts.append({"name": label, "configurations": len(cases), "operations": len(rows),
                       "wire_requests": values[wire], "maximum": values[maximum]})
        sources[{"extension": "extension", "async-boundary": "async", "sync-enforcement": "sync"}[phase]] = rows
        inputs[phase] = {"raw": f"results/raw/{phase}/records.jsonl", "raw_sha256": values["raw_sha256"],
                         "freeze": f"results/raw/{phase}/freeze.json", "freeze_sha256": resolver.sha256(raw / "freeze.json"),
                         "configurations": len(cases), "operations": len(rows),
                         "wire_requests": values[wire], "maximum_wire_requests": values[maximum]}
    return counts, sources, inputs


def migrations(root, sources, analyzer, resolver):
    manifest = load(root / "study/migration-pairs.json")
    require(len({s["id"] for s in manifest}) == len(manifest), "duplicate pair declarations")
    detailed, pairs = [], []
    for spec in manifest:
        allowed = {"id", "phase", "before", "after", "intent", "expected", "basis",
                   "directional_control", "observation_control"}
        require(set(spec) <= allowed, "unknown migration declaration field")
        for control in ("directional_control", "observation_control"):
            require(control not in spec or type(spec[control]) is bool, "migration control type")
        for side in ("before", "after"):
            require(set(spec[side]) <= {"id", "file", "mutate"}, "unknown migration selector field")
            if "mutate" in spec[side]:
                require(spec.get("observation_control") is True, "pair mutation outside declared observation control")
                same(spec[side]["mutate"], {"arrival_stream_complete": False}, "declared observation-loss mutation")
        require(spec["phase"] in PHASE_SOURCES, "unselected migration phase")
        before = analyzer.select(sources[spec["phase"]], spec["before"], spec["phase"])
        after = analyzer.select(sources[spec["phase"]], spec["after"], spec["phase"])
        seeds = analyzer.paired_seeds(before, after, spec["id"])
        categories, outcomes, wires = Counter(), Counter(), Counter()
        structural = 0
        for seed in seeds:
            result = analyzer.compare_migration(before[seed], after[seed], analyzer.AuditIntent(**spec["intent"]), pair_id=spec["id"])
            result.update(seed=seed, phase=spec["phase"], basis=spec["basis"], expected=spec["expected"])
            detailed.append(result)
            categories[result["category"]] += 1
            outcomes[analyzer.outcome_baseline(before[seed], after[seed])] += 1
            wires[analyzer.count_baseline(before[seed], after[seed])] += 1
            structural += int(result["structural_behavior_changed"])
        same(dict(categories), {spec["expected"]: len(seeds)}, f"pair category {spec['id']}")
        pairs.append({"id": spec["id"], "phase": spec["phase"], "n": len(seeds), "expected": spec["expected"],
                      "basis": spec["basis"], "directional_control": bool(spec.get("directional_control")),
                      "observation_control": bool(spec.get("observation_control")), "structural_changes": structural,
                      "outcome_prediction": ";".join(f"{k}:{v}" for k, v in sorted(outcomes.items())),
                      "count_prediction": ";".join(f"{k}:{v}" for k, v in sorted(wires.items())),
                      "outcome_correct": outcomes[analyzer.coarse(spec["expected"])],
                      "count_correct": wires[analyzer.coarse(spec["expected"])], "retryscope_correct": len(seeds)})
    real = [r for r in pairs if not r["directional_control"] and not r["observation_control"]]
    total = sum(r["n"] for r in pairs)
    summary = {
        "pair_types": len(pairs), "pair_observations": total, "real_pair_types": len(real),
        "real_pair_observations": sum(r["n"] for r in real),
        "directional_controls": sum(r["directional_control"] for r in pairs),
        "observation_controls": sum(r["observation_control"] for r in pairs),
        "expected_categories": dict(Counter(r["expected"] for r in pairs)),
        "retryscope_agreement": [sum(r["retryscope_correct"] for r in pairs), total],
        "outcome_only_agreement": [sum(r["outcome_correct"] for r in pairs), total],
        "flat_count_agreement": [sum(r["count_correct"] for r in pairs), total],
        "structural_change_observations": sum(r["structural_changes"] for r in pairs),
        "scope": "paired reanalysis of already executed immutable operations; controls are not additional independent cases",
        "initial_source": "client-witnessed rerun",
        "phase_sources": {p: {"pair_observations": sum(r["n"] for r in pairs if r["phase"] == p),
                              "collection": "current" if p == "initial" else "retained"} for p in PHASE_SOURCES},
        "initial_raw_sha256": {n: resolver.sha256(root / "results/raw/native-policy" / n)
                               for n in ("false.jsonl", "true.jsonl", "freeze.json")},
    }
    same(summary["phase_sources"], PHASE_SOURCES, "declared adopted pair counts")
    derived = root / "results/migration-derived"
    same(load(derived / "summary.json"), summary, "selected migration summary")
    same(jsonl(derived / "pairs.jsonl"), detailed, "selected migration details")
    with (derived / "pair-summary.csv").open(encoding="utf-8", newline="") as handle:
        same(list(csv.DictReader(handle)), [{k: str(v) for k, v in row.items()} for row in pairs],
             "selected pair table")
    return summary


def macros(path, expected, *, subset=False):
    text = path.read_text(encoding="utf-8")
    pattern = r"\\newcommand\{\\([A-Za-z]+)\}\{([^{}]*)\}"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    require(all(re.fullmatch(pattern, line) for line in lines), f"malformed count macros: {path}")
    entries = [re.fullmatch(pattern, line).groups() for line in lines]
    require(len(entries) == len({k for k, v in entries}), f"duplicate macros: {path}")
    actual = dict(entries)
    if subset:
        same(sorted(actual), sorted(set(expected) | {"ReferenceCount", "TestCount"}), "generator macro names")
        require(all(re.fullmatch(r"[0-9]+", actual[key]) for key in ("ReferenceCount", "TestCount")),
                "malformed ancillary generator counts (values outside selected-data check)")
        actual = {k: actual[k] for k in expected}
    same(actual, {k: str(v) for k, v in expected.items()}, f"count macros {path.name}")


def verify(root=ROOT, paper_dir=None):
    root = Path(root).resolve()
    data = load(root / "results/paper-data.json")
    same(data["policy_matrix"], "results/native-policy-derived", "adopted policy selection")
    with helpers(root) as (observed, analyzer, current, resolver):
        bindings = retained_sources(root, resolver)
        initial, native = policy(root, observed, resolver)
        retained, sources, retained_inputs = retained_counts(root, resolver)
        sources["initial"] = initial
        pairs = migrations(root, sources, analyzer, resolver)
        causal = jsonl(root / "results/raw/causal-witness/records.jsonl")
        for row in causal:
            require(type(row["seed"]) is int and type(row["concurrency"]) is int,
                    "causal seed/concurrency type")
            ids = {op["operation_id"] for op in row["operations"]}
            same(len(ids), len(row["operations"]), "unique causal operation ids")
            same(len(ids), row["concurrency"], "causal concurrency count")
            require(all(e["kind"] == "arrival" and e["witness_valid"] is True
                        and e["operation_id"] in ids for e in row["wire_events"]),
                    "causal counted arrival binding")
            same(row["score"]["operations"], len(ids), "causal stored operation count")
            same(row["score"]["wire_attempts"], len(row["wire_events"]), "causal stored wire count")
        keys = {(r["stack"], r["scenario"], r["concurrency"], r["seed"]) for r in causal}
        require(len(keys) == len(causal), "duplicate causal batch")
        configurations = {k[:3] for k in keys}
        operations = [op for r in causal for op in r["operations"]]
        arrivals = [e for r in causal for e in r["wire_events"] if e["kind"] == "arrival"]
        causal_counts = {"cells": len(causal), "operations": len(operations), "wire_attempts": len(arrivals)}
        causal_summary = load(root / "results/causal-derived/summary.json")
        for key, value in causal_counts.items():
            same(causal_summary[key], value, f"causal input {key}")
        maximum = max(max(Counter(e["operation_id"] for e in r["wire_events"]
                                  if e["kind"] == "arrival").values()) for r in causal)
        phases = [{"name": "Policy, HTTP, and integration", "configurations": native["cells"],
                   "operations": native["records"], "wire_requests": native["wire_requests"],
                   "maximum": native["maximum_wire_requests"]}, *retained,
                  {"name": "Concurrent causal attribution", "configurations": len(configurations),
                   "operations": len(operations), "wire_requests": len(arrivals), "maximum": maximum}]
        totals = {key: sum(row[key] for row in phases) for key in ("configurations", "operations", "wire_requests")}
        totals["maximum_wire_requests_per_operation"] = max(row["maximum"] for row in phases)
        expected = {"policy_matrix": "results/native-policy-derived", "policy_analysis_mode": "current",
                    "migration_pairs_use_retained_policy_records": False,
                    "migration_phase_sources": pairs["phase_sources"],
                    "phases": [{k: v for k, v in r.items() if k != "maximum"} for r in phases],
                    "totals": totals, "paired_migration_reuses_operations": pairs["pair_observations"],
                    "causal_seeded_batches": len(causal)}
        same(data, expected, "selected paper-data (all fields)")
        native_macros = {"ObservedRuns": native["records"], "ObservedCells": native["cells"],
                         "ObservedWires": native["wire_requests"], "ObservedMaxWires": native["maximum_wire_requests"],
                         "ObservedClientEvents": native["client_events"], "ObservedRetryArrivals": native["retry_arrivals"],
                         "ObservedPasses": native["audit_verdicts"].get("pass", 0),
                         "ObservedMismatches": native["audit_verdicts"].get("mismatch", 0),
                         "ObservedUnknowns": native["audit_verdicts"].get("unknown", 0),
                         "ServerOnlyUnknowns": native["server_only_counterfactual_verdicts"].get("unknown", 0)}
        pair_macros = {"MigrationPairTypes": pairs["pair_types"], "MigrationPairObservations": pairs["pair_observations"],
                       "MigrationRealPairTypes": pairs["real_pair_types"], "MigrationRealPairObservations": pairs["real_pair_observations"],
                       "MigrationOutcomeAgreement": pairs["outcome_only_agreement"][0],
                       "MigrationCountAgreement": pairs["flat_count_agreement"][0],
                       "MigrationStructuralChanges": pairs["structural_change_observations"]}
        macros(root / "results/native-policy-derived/observed-macros.tex", native_macros)
        macros(root / "results/migration-derived/migration-macros.tex", pair_macros)
        total_macros = {"TotalRuns": f"{totals['operations']:,}", "TotalCells": totals["configurations"],
                        "TotalWires": f"{totals['wire_requests']:,}",
                        "TotalMaxWires": totals["maximum_wire_requests_per_operation"]}
        if paper_dir is not None:
            generated = Path(paper_dir).resolve() / "generated"
            macros(generated / "observed-macros.tex", native_macros)
            macros(generated / "migration-macros.tex", pair_macros)
            macros(generated / "study-macros.tex", total_macros, subset=True)
        return {"schema": 1, "status": "passed", "route": "adopted-current-offline",
                "artifact_root": root.as_posix(), "all_history_verified": False,
                "historical_observed": "not selected; historical verifier unchanged, not run",
                "checks": {"current_complete_matrix_snapshot_trace_audit": "passed",
                           "retained_phase_source_bindings": bindings,
                           "retained_raw_matrices_counts_hashes": "passed",
                           "migration_details_summary_table": "passed", "paper_data_all_fields": "passed",
                           "selected_derived_count_macros": "passed",
                           "published_count_macros": "passed" if paper_dir is not None else "not requested"},
                "native_source_provenance": native["source_provenance"],
                "selection": {"policy_raw": "results/raw/native-policy", "policy_derived": data["policy_matrix"],
                              "migration_derived": "results/migration-derived",
                              "paper_dir": Path(paper_dir).resolve().as_posix() if paper_dir is not None else None},
                "initial_raw_sha256": pairs["initial_raw_sha256"],
                "retained_inputs": retained_inputs,
                "migration_manifest_sha256": resolver.sha256(root / "study/migration-pairs.json"),
                "source_map_sha256": resolver.sha256(root / "evidence/FROZEN-SOURCE-MAP.json"),
                "phase_sources": pairs["phase_sources"], "totals": totals,
                "generator_total_macros": total_macros,
                "scope": "Selected current policy exact replay, selected pair exact replay, retained source bindings and input-count closure. Not all-history verification, native recollection, retained metric regeneration, causal audit replay, reference or test-count validation."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="standalone artifact root (not project/paper root)")
    parser.add_argument("--paper-dir", type=Path, help="optional existing paper; read count macros only")
    args = parser.parse_args(argv)
    try:
        report = verify(args.root, args.paper_dir)
    except (Exception, SystemExit) as exc:
        report = {"schema": 1, "status": "hold", "route": "adopted-current-offline",
                  "all_history_verified": False, "error": str(exc)}
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

