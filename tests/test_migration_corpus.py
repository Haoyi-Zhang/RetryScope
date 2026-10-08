import csv
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_pair_manifest_is_unique_and_has_explicit_basis():
    rows=json.loads((ROOT/'study/migration-pairs.json').read_text())
    assert len(rows)==16
    assert len({r['id'] for r in rows})==len(rows)
    assert all(r.get('basis') and r.get('expected') and r.get('intent',{}).get('provenance') for r in rows)
    assert sum(bool(r.get('directional_control')) for r in rows)==1
    assert sum(bool(r.get('observation_control')) for r in rows)==1


def test_derived_pair_summary_matches_manifest_and_balancing():
    summary=json.loads((ROOT/'results/migration-derived/summary.json').read_text())
    assert summary['pair_types']==16
    assert summary['pair_observations']==96
    assert summary['real_pair_types']==14
    assert summary['real_pair_observations']==84
    assert summary['retryscope_agreement']==[96,96]
    assert summary['outcome_only_agreement']==[18,96]
    assert summary['flat_count_agreement']==[48,96]


def test_every_pair_type_has_six_immutable_replicates():
    with (ROOT/'results/migration-derived/pair-summary.csv').open(newline='') as stream:
        rows=list(csv.DictReader(stream))
    assert len(rows)==16
    assert {int(r['n']) for r in rows}=={6}
    assert sum(int(r['retryscope_correct']) for r in rows)==96


def test_pair_records_preserve_one_frozen_intent_per_type():
    rows=[json.loads(line) for line in (ROOT/'results/migration-derived/pairs.jsonl').read_text().splitlines() if line]
    grouped={}
    for row in rows:
        grouped.setdefault(row['pair_id'],set()).add(row['intent_fingerprint'])
        assert row['category']==row['expected']
        assert row['interpretation'].startswith('paired finite-trace conformance')
    assert len(grouped)==16 and all(len(fingerprints)==1 for fingerprints in grouped.values())
