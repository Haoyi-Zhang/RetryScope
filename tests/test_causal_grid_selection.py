"""A selected campaign cannot be empty or contain repeated deterministic cells."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def driver():
    spec = importlib.util.spec_from_file_location(
        'grid_selection_driver', ROOT/'scripts/causal_witness_study.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('option,value', [
    ('stacks', ''), ('scenarios', ''), ('concurrency', ''), ('seeds', ''),
    ('stacks', 'requests,,urllib3'), ('scenarios', 'retry,'),
    ('concurrency', ',1'), ('seeds', '11, '),
    ('stacks', 'requests,requests'), ('scenarios', 'retry,retry'),
    ('concurrency', '1,1'), ('seeds', '11,11'),
    ('concurrency', 'not-an-integer'), ('seeds', 'not-an-integer'),
    ('stacks', 'unknown'), ('scenarios', 'unknown'),
    ('concurrency', '3'), ('seeds', '0'),
])
def test_invalid_selection_rejected_before_output(tmp_path, monkeypatch, option, value):
    module = driver()
    output = tmp_path/'not-created'/'raw.jsonl'
    monkeypatch.setattr(sys, 'argv', ['study', '--output', str(output), '--'+option, value])
    monkeypatch.setattr(module, 'run_cell', lambda *a: pytest.fail('invalid grid executed'))
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 2
    assert not output.parent.exists()


def test_unique_supported_subset_executes_each_cell_once(tmp_path, monkeypatch):
    module = driver()
    output = tmp_path/'raw.jsonl'
    calls = []
    def run(*cell):
        calls.append(cell)
        return {'cell': list(cell), 'score': {'assignment_accuracy': {
            'causal_token': 1.0, 'timestamp_window': 1.0}, 'audit_verdicts': {'pass': 1}}}
    monkeypatch.setattr(module, 'run_cell', run)
    monkeypatch.setattr(sys, 'argv', ['study', '--output', str(output),
        '--stacks', ' requests, urllib3 ', '--scenarios', 'retry',
        '--concurrency', '1,2', '--seeds', '11'])
    module.main()
    assert calls == [('requests','retry',1,11), ('requests','retry',2,11),
                     ('urllib3','retry',1,11), ('urllib3','retry',2,11)]
    assert [json.loads(line)['cell'] for line in output.read_text().splitlines()] == [list(c) for c in calls]
