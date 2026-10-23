"""Apply one live checker to all retained paired inputs without rewriting history.

This is deterministic offline analysis. Missing historical owners remain missing;
neither fixture plans nor old verdicts are used to manufacture evidence.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from retryscope.audit import AuditIntent
from retryscope.migration import compare_migration
from analyze_migrations import read_jsonl, select, paired_seeds


def file_identity(path):
    data = path.read_bytes()
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def inputs():
    paths = ['study/migration-pairs.json', 'results/raw/native-policy/false.jsonl',
             'results/raw/native-policy/true.jsonl', 'results/raw/native-policy/freeze.json',
             'results/raw/extension/records.jsonl', 'results/raw/async-boundary/records.jsonl',
             'results/migration-derived/pairs.jsonl', 'results/migration-derived/summary.json',
             'src/retryscope/audit.py', 'src/retryscope/migration.py',
             'scripts/analyze_migrations.py', 'scripts/analyze_current_migrations.py']
    return {name: file_identity(ROOT / name) for name in paths}


def evaluate():
    started = datetime.now(timezone.utc).isoformat()
    bound = inputs()
    manifest = json.loads((ROOT / 'study/migration-pairs.json').read_text(encoding='utf-8'))
    initial = []
    for name in ('false', 'true'):
        for raw in read_jsonl(ROOT / f'results/raw/native-policy/{name}.jsonl'):
            row = dict(raw)
            row.update(_file=name, _observed_initial=True)
            initial.append(row)
    sources = {'initial': initial,
               'extension': read_jsonl(ROOT / 'results/raw/extension/records.jsonl'),
               'async': read_jsonl(ROOT / 'results/raw/async-boundary/records.jsonl')}
    retained = read_jsonl(ROOT / 'results/migration-derived/pairs.jsonl')
    old = {(row['pair_id'], row['seed']): row for row in retained}
    if len(old) != len(retained) or len(retained) != 96 or len(manifest) != 16:
        raise ValueError('Unexpected retained pair population')
    records = []
    for spec in manifest:
        phase = spec['phase']
        before = select(sources[phase], spec['before'], phase)
        after = select(sources[phase], spec['after'], phase)
        intent = AuditIntent(**spec['intent'])
        for seed in paired_seeds(before, after, spec['id']):
            prior = old[(spec['id'], seed)]
            if prior['phase'] != phase or prior['expected'] != spec['expected']:
                raise ValueError('Pair identity or retained manifest mismatch')
            current = compare_migration(before[seed], after[seed], intent, pair_id=spec['id'])
            records.append({'pair_id': spec['id'], 'seed': seed, 'phase': phase,
                            'expected_in_retained_design': spec['expected'],
                            'retained_category': prior['category'],
                            'retained_before': prior['before']['verdict'],
                            'retained_after': prior['after']['verdict'],
                            'current': current})
    if {(r['pair_id'], r['seed']) for r in records} != set(old) or len(records) != 96:
        raise ValueError('Current analysis did not cover every retained pair exactly once')
    if bound != inputs():
        raise ValueError('Raw input or live analysis source changed')
    by_phase = {}
    for phase in ('initial', 'extension', 'async'):
        rows = [r for r in records if r['phase'] == phase]
        dimensions = {}
        names = sorted({d for r in rows for d in r['current']['before']['dimensions']})
        for name in names:
            requested = [r for r in rows if name in r['current']['before']['dimensions']]
            if any(name not in r['current']['after']['dimensions'] for r in requested):
                raise ValueError('Before/after intent dimensions differ')
            dimensions[name] = {
                'requested_pairs': len(requested),
                'before': dict(sorted(Counter(r['current']['before']['dimensions'][name]['verdict'] for r in requested).items())),
                'after': dict(sorted(Counter(r['current']['after']['dimensions'][name]['verdict'] for r in requested).items())),
            }
        by_phase[phase] = {
            'pairs': len(rows),
            'retained_categories': dict(sorted(Counter(r['retained_category'] for r in rows).items())),
            'current_categories': dict(sorted(Counter(r['current']['category'] for r in rows).items())),
            'current_before_verdicts': dict(sorted(Counter(r['current']['before']['verdict'] for r in rows).items())),
            'current_after_verdicts': dict(sorted(Counter(r['current']['after']['verdict'] for r in rows).items())),
            'category_changed': sum(r['retained_category'] != r['current']['category'] for r in rows),
            'current_matches_retained_expected': sum(r['current']['category'] == r['expected_in_retained_design'] for r in rows),
            'requested_dimensions': dimensions,
        }
    summary = {'started_at_utc': started, 'completed_at_utc': datetime.now(timezone.utc).isoformat(),
               'source_and_input_bindings': bound, 'pair_types': 16, 'pair_observations': len(records),
               'phase_strata': by_phase,
               'retained_categories': dict(sorted(Counter(r['retained_category'] for r in records).items())),
               'current_categories': dict(sorted(Counter(r['current']['category'] for r in records).items())),
               'category_changed': sum(r['retained_category'] != r['current']['category'] for r in records),
               'scope': 'One live audit/paired checker applied to all unchanged retained phase inputs under the same manifest intents. Offline reanalysis, not new collection, recovered historical instrumentation or independent release decisions.',
               'historical_owner_backfilled': False, 'network_io_or_native_recollection': False}
    return records, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    if not out.is_relative_to((ROOT / 'results').resolve()) or out.exists():
        raise ValueError('Use a new analysis directory inside artifact/results')
    records, summary = evaluate()
    out.mkdir(parents=True)
    (out / 'pairs.jsonl').write_text(''.join(json.dumps(r, sort_keys=True, allow_nan=False) + '\n'
                                            for r in records), encoding='utf-8')
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
