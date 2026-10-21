"""Observed request identities cannot be hidden by a smaller reported count."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from retryscope.audit import AuditIntent, audit
from retryscope.migration import compare_migration


def record(count=1, *, complete=True):
    return {
        'arrivals': [{'id': i} for i in (1, 2, 3)],
        'wire_attempts_observed': count,
        'arrival_stream_complete': complete,
    }


@pytest.mark.parametrize('complete', [False, True])
def test_smaller_count_cannot_erase_witnessed_over_cap(complete):
    result = audit(record(complete=complete), AuditIntent(max_wire_attempts=2))
    assert result['verdict'] == 'mismatch'
    assert result['dimensions']['attempts']['observed'] == 3


def test_under_cap_count_contradiction_cannot_establish_pass():
    result = audit(record(), AuditIntent(max_wire_attempts=3))
    assert result['verdict'] == 'unknown'
    assert result['dimensions']['attempts']['observed'] == 3


@pytest.mark.parametrize('bad', [None, True, 1.0, -1, '1'])
def test_malformed_count_cannot_erase_independent_violation(bad):
    assert audit(record(bad), AuditIntent(max_wire_attempts=2))['verdict'] == 'mismatch'
    assert audit(record(bad), AuditIntent(max_wire_attempts=3))['verdict'] == 'unknown'


@pytest.mark.parametrize('explicit', [False, True])
def test_unusable_other_rows_do_not_erase_known_request_lower_bound(explicit):
    trace = record()
    trace['arrivals'].extend([{'id': None}, {'id': True}, None, {'id': 2}])
    if not explicit:
        trace.pop('wire_attempts_observed')
    assert audit(trace, AuditIntent(max_wire_attempts=2))['verdict'] == 'mismatch'


def test_duplicate_identity_does_not_inflate_lower_bound():
    trace = record(2)
    trace['arrivals'] = [{'id': 1}, {'id': 1}, {'id': 2}]
    assert audit(trace, AuditIntent(max_wire_attempts=2))['verdict'] == 'pass'
    trace.pop('wire_attempts_observed')
    assert audit(trace, AuditIntent(max_wire_attempts=2))['verdict'] == 'unknown'


def test_independent_inventory_may_exceed_attributed_projection():
    trace = record(3)
    trace['arrivals'] = [{'id': 1}]
    assert audit(trace, AuditIntent(max_wire_attempts=3))['verdict'] == 'pass'
    assert audit(trace, AuditIntent(max_wire_attempts=2))['verdict'] == 'mismatch'


def test_paired_comparison_preserves_violation():
    result = compare_migration(record(3), record(1), AuditIntent(max_wire_attempts=2))
    assert result['category'] == 'stable_nonconformant'
    assert result['before']['verdict'] == result['after']['verdict'] == 'mismatch'


def run_cli(tmp_path, trace, *, cap=2, before=None):
    trace_path = tmp_path / 'trace.json'
    intent_path = tmp_path / 'intent.json'
    trace_path.write_text(json.dumps(trace), encoding='utf-8')
    intent_path.write_text(json.dumps({'max_wire_attempts': cap}), encoding='utf-8')
    command = [sys.executable, '-m', 'retryscope.cli', '--trace', str(trace_path),
               '--intent', str(intent_path)]
    if before is not None:
        before_path = tmp_path / 'before.json'
        before_path.write_text(json.dumps(before), encoding='utf-8')
        command.extend(['--before', str(before_path)])
    env = os.environ.copy()
    source = str(Path(__file__).resolve().parents[1] / 'src')
    env['PYTHONPATH'] = source + os.pathsep + env.get('PYTHONPATH', '')
    return subprocess.run(command, capture_output=True, text=True, env=env,
                          check=False, timeout=20)


@pytest.mark.parametrize('complete', [False, True])
def test_real_cli_retains_witnessed_mismatch(tmp_path, complete):
    result = run_cli(tmp_path, record(complete=complete))
    assert result.returncode == 1, result.stderr or result.stdout
    assert json.loads(result.stdout)['verdict'] == 'mismatch'


def test_real_cli_does_not_accept_inconsistent_complete_inventory(tmp_path):
    result = run_cli(tmp_path, record(), cap=3)
    assert result.returncode == 2, result.stderr or result.stdout
    assert json.loads(result.stdout)['verdict'] == 'unknown'


@pytest.mark.parametrize('bad', [None, True, 1.0, -1, '1'])
def test_real_cli_rejects_malformed_explicit_count(tmp_path, bad):
    result = run_cli(tmp_path, record(bad))
    assert result.returncode == 3, result.stderr or result.stdout
    assert 'wire_attempts_observed' in result.stderr


def test_real_cli_paired_comparison_is_not_a_false_repair(tmp_path):
    result = run_cli(tmp_path, record(1), before=record(3))
    assert result.returncode == 1, result.stderr or result.stdout
    assert json.loads(result.stdout)['category'] == 'stable_nonconformant'
