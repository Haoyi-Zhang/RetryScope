import copy
import json
import pytest
from retryscope.audit import AuditIntent, audit
from retryscope.causal import WitnessLedger, deterministic_operation_id, join_causal_trace
from retryscope.cli import main


def captured():
    ledger = WitnessLedger(deterministic_operation_id('regression'))
    first = ledger.admit(role='initial', owner='client')
    second = ledger.admit(role='retry', owner='transport', parent=first,
                          cause={'kind': 'status', 'received_status': 503})
    wire = [dict(kind='arrival', global_index=t.ordinal, ordinal=t.ordinal,
                 operation_index=t.ordinal, operation_id=t.operation_id,
                 attempt_id=t.attempt_id, witness_valid=True) for t in (first, second)]
    return ledger, wire


@pytest.mark.parametrize('owner', [None, '', ' ', 3, 'x'*129])
def test_owner_is_required_without_losing_other_dimensions(owner):
    ledger, wire = captured()
    trace = join_causal_trace(ledger.events, wire, operation_id=ledger.operation_id,
                             outcome='success', payload='abc', payload_complete=True)
    trace['arrivals'][1]['owner'] = owner
    result = audit(trace, AuditIntent(max_wire_attempts=1, retryable_statuses=(503,),
                                     expected_payload='abc', required_outcome='success'))
    assert result['dimensions']['classification']['verdict'] == 'unknown'
    assert result['dimensions']['attempts']['verdict'] == 'mismatch'
    assert result['dimensions']['payload']['verdict'] == 'pass'
    assert result['dimensions']['outcome']['verdict'] == 'pass'
    assert result['verdict'] == 'mismatch'


@pytest.mark.parametrize('mutation', ['ordinal', 'inventory'])
def test_capture_contradictions_prevent_complete_join(mutation):
    ledger, wire = captured()
    if mutation == 'ordinal':
        wire[1]['ordinal'] = 1
    else:
        bad = copy.deepcopy(wire[1]); bad['global_index'] = None
        wire.append(bad)
    trace = join_causal_trace(ledger.events, wire, operation_id=ledger.operation_id)
    assert not trace['causal_join_complete']
    assert trace['causal_errors']
    assert audit(trace, AuditIntent(retryable_statuses=(503,)))['verdict'] == 'unknown'


def test_unknown_role_survives_join_to_audit_cli(tmp_path):
    ledger, wire = captured()
    trace = join_causal_trace(ledger.events[:1], wire, operation_id=ledger.operation_id)
    assert trace['arrivals'][1]['role'] == 'unknown'
    path = tmp_path/'trace.json'; path.write_text(json.dumps(trace))
    intent = tmp_path/'intent.json'; intent.write_text(json.dumps({'max_wire_attempts': 1}))
    assert main(['--trace', str(path), '--intent', str(intent)]) == 1
