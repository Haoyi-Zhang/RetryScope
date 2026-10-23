"""Validate the live-checker reanalysis against every retained pair, then export."""
import argparse
import json
from pathlib import Path
from analyze_current_migrations import ROOT, evaluate, read_jsonl

SELECTED = ROOT / 'results/current-migration-derived'


def verify(records, summary):
    expected_records, expected_summary = evaluate()
    ignored = {'started_at_utc', 'completed_at_utc'}
    stable = lambda value: {k: v for k, v in value.items() if k not in ignored}
    if records != expected_records:
        raise ValueError('Selected current pair details differ from live reanalysis')
    if stable(summary) != stable(expected_summary):
        raise ValueError('Selected current summary or source/input binding differs')
    return summary


def read_current():
    records = read_jsonl(SELECTED / 'pairs.jsonl')
    summary = json.loads((SELECTED / 'summary.json').read_text(encoding='utf-8'))
    return verify(records, summary)


def render(summary):
    rows = []
    for phase, label in [('initial', 'Policy capture'), ('extension', 'Extension'), ('async', 'Async')]:
        values = summary['phase_strata'][phase]
        triple = lambda side: '/'.join(str(values[f'current_{side}_verdicts'].get(k, 0))
                                      for k in ('pass', 'mismatch', 'unknown'))
        requested = values['requested_dimensions'].get('classification', {}).get('requested_pairs', 0)
        rows.append(f"{label} & {values['pairs']} & {requested} & {triple('before')} & {triple('after')} \\\\")
    macros = {'CurrentMigrationPairs': summary['pair_observations'],
              'CurrentMigrationChanged': summary['category_changed'],
              'CurrentMigrationAfterUnknown': sum(x['current_after_verdicts'].get('unknown', 0)
                                                 for x in summary['phase_strata'].values())}
    return '\n'.join(rows) + '\n', ''.join(f'\\newcommand{{\\{k}}}{{{v}}}\n' for k, v in macros.items())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--paper-dir', type=Path)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    summary = read_current()
    if args.paper_dir and not args.check_only:
        generated = args.paper_dir / 'generated'
        generated.mkdir(parents=True, exist_ok=True)
        rows, macros = render(summary)
        (generated / 'current-migration-rows.tex').write_text(rows, encoding='utf-8')
        (generated / 'current-migration-macros.tex').write_text(macros, encoding='utf-8')
    print(json.dumps({'status': 'pass', 'pairs_reanalyzed': summary['pair_observations'],
                      'category_changes': summary['category_changed'],
                      'current_categories': summary['current_categories'],
                      'scope': summary['scope']}))


if __name__ == '__main__':
    main()
