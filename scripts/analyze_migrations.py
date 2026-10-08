#!/usr/bin/env python3
"""Build the paired migration evaluation from immutable executed traces."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from retryscope.audit import AuditIntent, from_legacy
from retryscope.migration import compare_migration


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_sources(initial_raw: Path | None) -> dict[str, list[dict[str, Any]]]:
    initial = []
    base = initial_raw or ROOT / "results/raw/evaluation"
    for name in ("false", "true"):
        for row in read_jsonl(base / f"{name}.jsonl"):
            row = dict(row)
            row["_file"] = name
            row["_observed_initial"] = initial_raw is not None
            initial.append(row)
    return {
        "initial": initial,
        "extension": read_jsonl(ROOT / "results/raw/extension/records.jsonl"),
        "async": read_jsonl(ROOT / "results/raw/async-boundary/records.jsonl"),
    }


def key(row: dict[str, Any], phase: str) -> Any:
    """Return the replicate identifier shared by both sides of a pair.

    Operation ids intentionally differ across migration phases, so they cannot be
    part of the join key. Every recorded phase uses a predeclared seed as its
    immutable replicate identifier.
    """
    seed = row.get("seed")
    if seed is None:
        raise ValueError(f"record {row.get('id')} has no pairing seed")
    return seed


def normalize(row: dict[str, Any], phase: str) -> dict[str, Any]:
    if phase == "initial":
        if row.get("_observed_initial"):
            out = dict(row["audit_trace"])
            out["wire_attempts"] = row.get("wire_attempts")
            return out
        out = from_legacy(row)
        out["wire_attempts"] = row.get("wire_attempts")
        return out
    return dict(row)


def select(rows: list[dict[str, Any]], selector: dict[str, Any], phase: str) -> dict[Any, dict[str, Any]]:
    picked: dict[Any, dict[str, Any]] = {}
    for row in rows:
        if row.get("id") != selector["id"]:
            continue
        if "file" in selector and row.get("_file") != selector["file"]:
            continue
        normalized = normalize(row, phase)
        for field, value in selector.get("mutate", {}).items():
            normalized[field] = value
        picked[key(row, phase)] = normalized
    return picked


def coarse(category: str) -> str:
    if category in ("repair", "regression", "evidence_loss", "evidence_gain"):
        return category
    return "stable"


def outcome_baseline(before: dict[str, Any], after: dict[str, Any]) -> str:
    b, a = before.get("outcome"), after.get("outcome")
    if b == "error" and a == "success":
        return "repair"
    if b == "success" and a == "error":
        return "regression"
    return "stable"


def count_baseline(before: dict[str, Any], after: dict[str, Any]) -> str:
    def n(row: dict[str, Any]) -> int | None:
        if isinstance(row.get("arrivals"), list):
            return len(row["arrivals"])
        return row.get("wire_attempts") if isinstance(row.get("wire_attempts"), int) else None
    b, a = n(before), n(after)
    if b is None or a is None:
        return "unknown"
    if a < b:
        return "repair"
    if a > b:
        return "regression"
    return "stable"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--paper-dir", type=Path)
    ap.add_argument("--initial-raw", type=Path, help="client-witnessed initial matrix; omit for legacy conversion")
    ap.add_argument("--manifest", type=Path, default=ROOT / "study/migration-pairs.json")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)

    manifest = json.loads(args.manifest.read_text())
    sources = load_sources(args.initial_raw)
    pair_rows: list[dict[str, Any]] = []
    detailed: list[dict[str, Any]] = []

    for spec in manifest:
        phase = spec["phase"]
        before = select(sources[phase], spec["before"], phase)
        after = select(sources[phase], spec["after"], phase)
        common = sorted(set(before) & set(after))
        if not common:
            raise RuntimeError(f"no paired records for {spec['id']}")
        # Balance all pair types to six executed pair observations.
        common = common[:6]
        intent = AuditIntent(**spec["intent"])
        categories = Counter()
        expected = spec["expected"]
        outcome_predictions = Counter()
        count_predictions = Counter()
        structural_changes = 0
        for k in common:
            result = compare_migration(before[k], after[k], intent, pair_id=spec["id"])
            result.update(seed=k, phase=phase, basis=spec["basis"], expected=expected)
            detailed.append(result)
            categories[result["category"]] += 1
            outcome_predictions[outcome_baseline(before[k], after[k])] += 1
            count_predictions[count_baseline(before[k], after[k])] += 1
            structural_changes += int(result["structural_behavior_changed"])
        if categories != Counter({expected: len(common)}):
            raise AssertionError(f"unexpected category for {spec['id']}: {categories}, expected {expected}")
        expected_coarse = coarse(expected)
        outcome_correct = outcome_predictions[expected_coarse]
        count_correct = count_predictions[expected_coarse]
        pair_rows.append({
            "id": spec["id"], "phase": phase, "n": len(common), "expected": expected,
            "basis": spec["basis"], "directional_control": bool(spec.get("directional_control")),
            "observation_control": bool(spec.get("observation_control")),
            "structural_changes": structural_changes,
            "outcome_prediction": ";".join(f"{k}:{v}" for k,v in sorted(outcome_predictions.items())),
            "count_prediction": ";".join(f"{k}:{v}" for k,v in sorted(count_predictions.items())),
            "outcome_correct": outcome_correct, "count_correct": count_correct,
            "retryscope_correct": len(common),
        })

    with (args.out / "pairs.jsonl").open("w") as f:
        for row in detailed:
            f.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
    fields = list(pair_rows[0])
    with (args.out / "pair-summary.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(pair_rows)

    real = [r for r in pair_rows if not r["directional_control"] and not r["observation_control"]]
    directional = [r for r in pair_rows if r["directional_control"]]
    observation = [r for r in pair_rows if r["observation_control"]]
    summary = {
        "pair_types": len(pair_rows),
        "pair_observations": sum(r["n"] for r in pair_rows),
        "real_pair_types": len(real),
        "real_pair_observations": sum(r["n"] for r in real),
        "directional_controls": len(directional),
        "observation_controls": len(observation),
        "expected_categories": dict(Counter(r["expected"] for r in pair_rows)),
        "retryscope_agreement": [sum(r["retryscope_correct"] for r in pair_rows), sum(r["n"] for r in pair_rows)],
        "outcome_only_agreement": [sum(r["outcome_correct"] for r in pair_rows), sum(r["n"] for r in pair_rows)],
        "flat_count_agreement": [sum(r["count_correct"] for r in pair_rows), sum(r["n"] for r in pair_rows)],
        "structural_change_observations": sum(r["structural_changes"] for r in pair_rows),
        "scope": "paired reanalysis of already executed immutable operations; controls are not additional independent cases",
        "initial_source": "client-witnessed rerun" if args.initial_raw else "legacy server-only conversion",
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    # Compact LaTeX rows for the manuscript.
    labels = {
        "aws_default_policy_opt_in": "AWS policy opt-in",
        "boto_total_attempt_normalization": "Boto count normalization",
        "requests_total_normalization": "Requests count normalization",
        "hub_total_normalization": "Hub count normalization",
        "broad_to_selective_400": "Broad to selective 400",
        "nested_retry_owner_normalization": "Nested retry ownership",
        "native_http_upgrade_truncation": "Native truncation upgrade",
        "body_aware_upgrade_adaptation": "Body-aware adaptation",
        "pooch_enable_registered_hash_retry": "Pooch hash enablement",
        "requests_enable_digest_retry": "Requests digest enablement",
        "fsspec_metadata_discovery": "fsspec metadata discovery",
        "fsspec_block_size_change": "fsspec block-size change",
        "async_trickle_total_timeout": "Trickle total timeout",
        "async_retry_delay_total_timeout": "Retry-delay total timeout",
    }
    tex=[]
    for r in real:
        tex.append(f"{labels[r['id']]} & {r['expected'].replace('_',' ')} & {r['outcome_prediction']} & {r['count_prediction']} \\\\")
    (args.out / "migration-rows.tex").write_text("\n".join(tex)+"\n")

    category_rows=[]
    category_labels={
        "stable_conformant":"Stable pass",
        "repair":"Repair",
        "regression":"Regression control",
        "stable_nonconformant":"Stable mismatch",
        "evidence_loss":"Evidence-loss control",
    }
    for category in ("stable_conformant", "repair", "regression", "stable_nonconformant", "evidence_loss"):
        subset=[r for r in pair_rows if r["expected"] == category]
        if not subset:
            continue
        category_rows.append(
            f"{category_labels[category]} & {len(subset)} & {sum(r['n'] for r in subset)} & "
            f"{sum(r['outcome_correct'] for r in subset)}/{sum(r['n'] for r in subset)} & "
            f"{sum(r['count_correct'] for r in subset)}/{sum(r['n'] for r in subset)} \\\\"
        )
    (args.out / "migration-category-rows.tex").write_text("\n".join(category_rows)+"\n")
    macros = {
        "MigrationPairTypes": summary["pair_types"],
        "MigrationPairObservations": summary["pair_observations"],
        "MigrationRealPairTypes": summary["real_pair_types"],
        "MigrationRealPairObservations": summary["real_pair_observations"],
        "MigrationOutcomeAgreement": summary["outcome_only_agreement"][0],
        "MigrationCountAgreement": summary["flat_count_agreement"][0],
        "MigrationStructuralChanges": summary["structural_change_observations"],
    }
    macro_text="\n".join(f"\\newcommand{{\\{name}}}{{{value}}}" for name,value in macros.items())+"\n"
    (args.out / "migration-macros.tex").write_text(macro_text)
    if args.paper_dir:
        generated=args.paper_dir / "generated"
        generated.mkdir(parents=True,exist_ok=True)
        for name in ("migration-rows.tex", "migration-category-rows.tex", "migration-macros.tex"):
            (generated/name).write_bytes((args.out/name).read_bytes())
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
