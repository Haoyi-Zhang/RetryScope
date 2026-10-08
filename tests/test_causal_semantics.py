from copy import deepcopy
from dataclasses import replace
import importlib.util
from pathlib import Path
import pytest
from retryscope.audit import AuditIntent, audit
from retryscope.causal import WitnessLedger, deterministic_operation_id, join_causal_trace

def fixture():
    ledger = WitnessLedger(deterministic_operation_id('semantic-test'))
    first = ledger.admit(role='initial', owner='client')
    second = ledger.admit(role='retry', owner='policy', parent=first,
                          cause={'kind': 'status', 'received_status': 503, 'detail': {'labels': ['a']}})
    wire = [dict(kind='arrival', global_index=t.ordinal, operation_index=t.ordinal,
                 operation_id=t.operation_id, attempt_id=t.attempt_id, witness_valid=True, t_ns=t.ordinal)
            for t in (first, second)]
    return ledger, first, second, wire

def test_inventory_is_not_attribution():
    ledger, first, _, wire = fixture()
    wire[1]['attempt_id'] = first.attempt_id
    trace = join_causal_trace(ledger.events, wire, operation_id=ledger.operation_id)
    result = audit(trace, AuditIntent(max_wire_attempts=1, retryable_statuses=(503,)))
    assert result['dimensions']['attempts']['verdict'] == 'mismatch'
    assert result['dimensions']['classification']['verdict'] == 'unknown'
    assert trace['arrivals'] == []

def test_log_replay_is_not_an_extra_request():
    ledger, _, _, wire = fixture()
    trace = join_causal_trace(ledger.events, wire + [deepcopy(wire[0])], operation_id=ledger.operation_id)
    assert trace['wire_attempts_observed'] == 2
    assert audit(trace, AuditIntent(max_wire_attempts=2))['verdict'] == 'pass'

def test_boundary_completion_is_explicit():
    ledger, _, _, wire = fixture()
    trace = join_causal_trace(ledger.events, wire, operation_id=ledger.operation_id,
                             outcome='success', payload='ok', elapsed_s=.01)
    assert audit(trace, AuditIntent(expected_payload='ok', budget_s=.1))['verdict'] == 'unknown'
    trace = join_causal_trace(ledger.events, wire, operation_id=ledger.operation_id,
                             body_elapsed_s=.03, body_complete=True,
                             cleanup_elapsed_s=.4, cleanup_complete=True)
    assert audit(trace, AuditIntent(budget_s=.1, boundary='body'))['verdict'] == 'pass'
    assert audit(trace, AuditIntent(budget_s=.1, boundary='cleanup'))['verdict'] == 'mismatch'

def test_snapshots_are_isolated_and_forged_fields_rejected():
    ledger, _, ticket, _ = fixture()
    events = ledger.events
    events[-1]['cause']['detail']['labels'].append('changed')
    ticket.cause['detail']['labels'].append('also changed')
    assert ledger.events[-1]['cause']['detail']['labels'] == ['a']
    pristine = ledger.tickets[-1]
    for field in (dict(ordinal=7), dict(owner='other')):
        with pytest.raises(ValueError, match='ticket'):
            ledger.headers(replace(pristine, **field))
        with pytest.raises(ValueError, match='ticket'):
            ledger.complete(replace(pristine, **field), status=200)

def test_scoring_uses_prediction_not_reference(monkeypatch):
    path = Path(__file__).parents[1] / 'scripts' / 'causal_witness_study.py'
    spec = importlib.util.spec_from_file_location('causal_witness_study', path)
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    ledger, _, _, wire = fixture()
    result = module.OperationResult(ledger.operation_id, ledger.events, 'success', 'ok', True, .01, None)
    correct = module._score_batch([result], wire, 'retry')
    assert correct['owner_accuracy']['causal_token'] == 1
    original = module.join_causal_trace
    def wrong(*args, **kwargs):
        trace = original(*args, **kwargs)
        trace['arrivals'][1]['owner'] = 'wrong'
        return trace
    monkeypatch.setattr(module, 'join_causal_trace', wrong)
    actual = module._score_batch([result], wire, 'retry')
    assert actual['owner_accuracy']['causal_token'] == .5
    assert actual['edge_metrics']['causal_token']['f1'] == 0
