"""Owned deterministic receipt perturbations; no collection or network activity."""
import json
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import current_migration_receipt as receipt


def selected():
    records = receipt.read_jsonl(receipt.SELECTED / 'pairs.jsonl')
    summary = json.loads((receipt.SELECTED / 'summary.json').read_text(encoding='utf-8'))
    return records, summary


def test_one_checker_covers_all_retained_pairs_without_adding_owner():
    records, summary = selected()
    actual = receipt.verify(records, summary)
    assert actual['pair_observations'] == 96
    assert actual['category_changed'] == 0
    assert actual['historical_owner_backfilled'] is False
    extension = actual['phase_strata']['extension']
    assert extension['pairs'] == 30
    assert 'classification' not in extension['requested_dimensions']
    assert extension['current_after_verdicts'] == {'pass': 24, 'unknown': 6}


@pytest.mark.parametrize('defect', ['missing_pair', 'changed_category', 'changed_verdict',
                                  'wrong_phase_count', 'source_identity', 'invented_owner'])
def test_selected_details_or_summary_cannot_override_real_inputs(defect):
    records, summary = selected()
    if defect == 'missing_pair':
        records.pop()
    elif defect == 'changed_category':
        records[0]['current']['category'] = 'inconclusive'
    elif defect == 'changed_verdict':
        records[0]['current']['after']['verdict'] = 'unknown'
    elif defect == 'wrong_phase_count':
        summary['phase_strata']['extension']['pairs'] -= 1
    elif defect == 'source_identity':
        summary['source_and_input_bindings']['src/retryscope/audit.py']['sha256'] = '0' * 64
    elif defect == 'invented_owner':
        summary['historical_owner_backfilled'] = True
    with pytest.raises(ValueError):
        receipt.verify(records, summary)


def test_check_only_does_not_write_manuscript_or_results(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['current_migration_receipt.py', '--check-only'])
    monkeypatch.setattr(Path, 'write_text', lambda *args, **kwargs: pytest.fail('read-only check wrote a file'))
    receipt.main()


def test_table_rows_use_requested_dimensions_not_historical_success_claims():
    _, summary = selected()
    rows, macros = receipt.render(summary)
    assert 'Policy capture & 54 & 54 & 12/42/0 & 42/12/0' in rows
    assert 'Extension & 30 & 0 & 18/12/0 & 24/0/6' in rows
    assert 'Async & 12 & 0 & 0/12/0 & 12/0/0' in rows
    assert r'\newcommand{\CurrentMigrationChanged}{0}' in macros
