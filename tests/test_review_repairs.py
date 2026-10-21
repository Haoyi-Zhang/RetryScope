"""Owned offline regressions: toy evidence only, no collection or network."""
from copy import deepcopy
import json

import pytest

from retryscope.audit import AuditIntent, audit
from retryscope.causal import join_causal_trace
from retryscope.causal_cli import _load_events, main as join_main
from retryscope.cli import main as audit_main, strict_load
from retryscope.migration import compare_migration


PERMISSIONS = [
    ('allow_body_recovery', 'body_error'),
    ('allow_transport_retry', 'transport_error'),
    ('allow_integrity_retry', 'content_mismatch'),
]


def trace(kind='status', status=400):
    return {
        'arrivals': [
            {'id': 1, 'role': 'initial', 'attribution_witness': 'owned entry'},
            {'id': 2, 'role': 'retry', 'owner': 'owned policy', 'retry_of': 1,
             'cause': {'kind': kind, 'received_status': status},
             'attribution_witness': 'owned decision'},
        ],
        'arrival_stream_complete': True, 'retry_attribution_complete': True,
    }


@pytest.mark.parametrize('field,kind', PERMISSIONS)
@pytest.mark.parametrize('value', ['false', 'true', '', 0, 1, 0.0, 1.0, None, [], {}])
def test_permission_type_rejected_by_library_and_cli(tmp_path, capsys, field, kind, value):
    with pytest.raises(ValueError, match=field):
        AuditIntent(**{field: value})
    t, i = tmp_path / 'trace.json', tmp_path / 'intent.json'
    t.write_text(json.dumps(trace(kind)), encoding='utf8')
    i.write_text(json.dumps({'retryable_statuses': [503], field: value}), encoding='utf8')
    assert audit_main(['--trace', str(t), '--intent', str(i)]) == 3
    output = capsys.readouterr()
    assert output.out == '' and field in output.err


@pytest.mark.parametrize('field,kind', PERMISSIONS)
@pytest.mark.parametrize('value,verdict,code', [(False, 'mismatch', 1), (True, 'pass', 0)])
def test_real_boolean_permissions(tmp_path, capsys, field, kind, value, verdict, code):
    intent = {'retryable_statuses': [503], field: value}
    assert audit(trace(kind), AuditIntent(**intent))['verdict'] == verdict
    t, i = tmp_path / 'trace.json', tmp_path / 'intent.json'
    t.write_text(json.dumps(trace(kind)), encoding='utf8')
    i.write_text(json.dumps(intent), encoding='utf8')
    assert audit_main(['--trace', str(t), '--intent', str(i)]) == code
    assert json.loads(capsys.readouterr().out)['verdict'] == verdict


def streams():
    op = '1' * 32
    clients = [
        {'kind': 'admission', 'operation_id': op, 'attempt_id': f'{n:016x}',
         'ordinal': n, 'role': 'initial' if n == 1 else 'retry', 'owner': 'owned policy',
         'parent_attempt_id': None if n == 1 else f'{1:016x}',
         'cause': None if n == 1 else {'kind': 'status', 'received_status': 400}}
        for n in (1, 2)
    ]
    wires = [
        {'kind': 'arrival', 'operation_id': op, 'attempt_id': row['attempt_id'],
         'ordinal': row['ordinal'], 'global_index': row['ordinal'],
         'operation_index': row['ordinal'], 'witness_valid': True}
        for row in clients
    ]
    return op, clients, wires


def event_text(rows, suffix):
    return '\n\n' + '\n'.join(json.dumps(row) for row in rows) + '\n' if suffix == 'jsonl' else json.dumps(rows)


@pytest.mark.parametrize('client_suffix', ['json', 'jsonl'])
@pytest.mark.parametrize('wire_suffix', ['json', 'jsonl'])
def test_legitimate_event_formats_are_equivalent(tmp_path, capsys, client_suffix, wire_suffix):
    op, clients, wires = streams()
    c, w = tmp_path / ('c.' + client_suffix), tmp_path / ('w.' + wire_suffix)
    c.write_text(event_text(clients, client_suffix), encoding='utf8')
    w.write_text(event_text(wires, wire_suffix), encoding='utf8')
    assert _load_events(c) == clients and _load_events(w) == wires
    assert join_main(['--client-events', str(c), '--wire-events', str(w),
                      '--operation-id', op, '--stream-complete']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['causal_join_complete'] is True
    assert audit(result, AuditIntent(retryable_statuses=(503,)))['verdict'] == 'mismatch'


DUPLICATES = [
    '"role":"retry","role":"initial"',
    '"owner":"one","owner":"two"',
    '"operation_id":"one","operation_id":"two"',
    '"attempt_id":"one","attempt_id":"two"',
    '"ordinal":1,"ordinal":2',
    '"cause":{"kind":"status","received_status":400,"received_status":503}',
    '"extra":{"owner":"one","owner":"two"}',
]
NONFINITE = ['"extra":' + value for value in ('NaN', 'Infinity', '-Infinity', '1e999', '-1e999')]


@pytest.mark.parametrize('suffix', ['json', 'jsonl'])
@pytest.mark.parametrize('side', ['client', 'wire'])
@pytest.mark.parametrize('fragment', DUPLICATES + NONFINITE)
def test_event_parser_rejects_ambiguous_or_nonfinite_json(tmp_path, capsys, suffix, side, fragment):
    op, clients, wires = streams()
    c, w = tmp_path / ('c.' + suffix), tmp_path / ('w.' + suffix)
    c.write_text(event_text(clients, suffix), encoding='utf8')
    w.write_text(event_text(wires, suffix), encoding='utf8')
    target = c if side == 'client' else w
    bad = '{' + fragment + '}'
    target.write_text('\n\n' + bad + '\n' if suffix == 'jsonl' else '[' + bad + ']', encoding='utf8')
    with pytest.raises(ValueError, match='duplicate JSON field|non-finite JSON number'):
        _load_events(target)
    assert join_main(['--client-events', str(c), '--wire-events', str(w),
                      '--operation-id', op, '--stream-complete']) == 3
    output = capsys.readouterr()
    assert not output.out
    assert 'duplicate JSON field' in output.err or 'non-finite JSON number' in output.err
    if suffix == 'jsonl':
        assert 'line 3' in output.err


@pytest.mark.parametrize('text', ['{"x":NaN}', '{"x":Infinity}', '{"x":-Infinity}',
                                '{"x":1e999}', '{"x":-1e999}', '{"x":1,"x":2}'])
def test_audit_json_loader_uses_same_strict_policy(tmp_path, text):
    p = tmp_path / 'input.json'
    p.write_text(text, encoding='utf8')
    with pytest.raises(ValueError):
        strict_load(p)


@pytest.mark.parametrize('text', ['[]', 'null', 'true', '1', '{broken', '{"x":1} trailing'])
def test_jsonl_shape_and_syntax_errors_have_line_numbers(tmp_path, text):
    p = tmp_path / 'bad.jsonl'
    p.write_text('\n\n' + text, encoding='utf8')
    with pytest.raises(ValueError, match='line 3'):
        _load_events(p)


@pytest.mark.parametrize('bad', [None, [], 'bad', {'id': None}, {'id': True},
                                     {'id': 1.0}, {'id': '1'}, {'id': 0}, {'id': -1},
                                     {'id': 3, 'role': 'unknown'}])
@pytest.mark.parametrize('position', [0, 1, 2])
def test_unrelated_malformed_arrival_does_not_erase_violation(bad, position):
    r = trace()
    r['arrivals'].insert(position, deepcopy(bad))
    result = audit(r, AuditIntent(retryable_statuses=(503,)))
    assert result['dimensions']['classification']['verdict'] == 'mismatch'
    assert result['verdict'] == 'mismatch'
    assert any(row['id'] == 2 and row['verdict'] == 'mismatch'
               for row in result['dimensions']['classification']['requests'])


@pytest.mark.parametrize('bad', [None, {'id': None}, {'id': 3, 'role': 'unknown'}])
def test_partial_permitted_evidence_cannot_prove_pass(bad):
    r = trace(status=503)
    r['arrivals'].append(bad)
    assert audit(r, AuditIntent(retryable_statuses=(503,)))['verdict'] == 'unknown'


@pytest.mark.parametrize('identity', [1, 2])
@pytest.mark.parametrize('mutation', [{}, {'owner': 'conflicting policy'}, {'role': 'unknown'},
                                     {'cause': None}, {'attribution_witness': None}])
@pytest.mark.parametrize('position', [0, 2])
def test_duplicate_parent_or_child_identity_never_selects_a_record(identity, mutation, position):
    r = trace()
    duplicate = deepcopy(r['arrivals'][identity - 1])
    duplicate.update(mutation)
    r['arrivals'].insert(position, duplicate)
    assert audit(r, AuditIntent(retryable_statuses=(503,)))['verdict'] == 'unknown'


@pytest.mark.parametrize('change', [
    {'retry_of': 99}, {'retry_of': 2}, {'retry_of': True}, {'retry_of': 1.0},
    {'retry_of': None}, {'owner': ''}, {'owner': None}, {'cause': None},
    {'attribution_witness': None},
])
def test_missing_or_malformed_local_edge_abstains(change):
    r = trace()
    r['arrivals'][1].update(change)
    assert audit(r, AuditIntent(retryable_statuses=(503,)))['verdict'] == 'unknown'


@pytest.mark.parametrize('mode', ['missing_root', 'unknown_root', 'root_without_witness',
                                  'duplicate_root', 'cycle', 'forward', 'bad_middle_owner'])
def test_entire_parent_chain_must_be_unambiguous(mode):
    r = trace(status=503)
    child = deepcopy(r['arrivals'][1])
    child.update(id=3, retry_of=2, cause={'kind': 'status', 'received_status': 400})
    r['arrivals'].append(child)
    if mode == 'missing_root':
        r['arrivals'].pop(0)
    elif mode == 'unknown_root':
        r['arrivals'][0]['role'] = 'unknown'
    elif mode == 'root_without_witness':
        r['arrivals'][0].pop('attribution_witness')
    elif mode == 'duplicate_root':
        r['arrivals'].append(deepcopy(r['arrivals'][0]))
    elif mode == 'cycle':
        r['arrivals'][0]['retry_of'] = 3
    elif mode == 'forward':
        r['arrivals'][1]['retry_of'] = 3
    else:
        r['arrivals'][1]['owner'] = ''
    assert audit(r, AuditIntent(retryable_statuses=(503,)))['verdict'] == 'unknown'


def test_valid_parent_chain_is_order_independent_and_keeps_violation():
    r = trace(status=503)
    child = deepcopy(r['arrivals'][1])
    child.update(id=3, retry_of=2, cause={'kind': 'status', 'received_status': 400})
    r['arrivals'] = [child, r['arrivals'][1], {'id': None}, r['arrivals'][0]]
    assert audit(r, AuditIntent(retryable_statuses=(503,)))['verdict'] == 'mismatch'


def test_unknown_parent_cause_does_not_erase_witnessed_child_violation():
    r = trace(kind='unclassified_received_cause')
    child = deepcopy(r['arrivals'][1])
    child.update(id=3, retry_of=2, cause={'kind': 'status', 'received_status': 400})
    r['arrivals'].append(child)
    result = audit(r, AuditIntent(retryable_statuses=(503,)))
    assert result['verdict'] == 'mismatch'
    assert [row['verdict'] for row in result['dimensions']['classification']['requests']] == [
        'pass', 'unknown', 'mismatch',
    ]


def test_unrelated_duplicate_identity_does_not_erase_unique_chain():
    r = trace()
    r['arrivals'] += [{'id': 8, 'role': 'unknown'}, {'id': 8, 'role': 'initial'}]
    assert audit(r, AuditIntent(retryable_statuses=(503,)))['verdict'] == 'mismatch'


@pytest.mark.parametrize('mode', ['duplicate_client_owner', 'duplicate_malformed_client',
                                  'duplicate_wire', 'duplicate_invalid_wire', 'ordinal_conflict'])
@pytest.mark.parametrize('reverse', [False, True])
def test_join_does_not_certify_ambiguous_local_witness(mode, reverse):
    op, clients, wires = streams()
    if mode.startswith('duplicate_client') or mode == 'duplicate_malformed_client':
        extra = deepcopy(clients[1])
        extra['owner'] = '' if mode == 'duplicate_malformed_client' else 'other policy'
        clients.append(extra)
    elif mode.startswith('duplicate_'):
        extra = deepcopy(wires[1])
        extra['global_index'] = 3
        if mode == 'duplicate_invalid_wire':
            extra['witness_valid'] = False
        wires.append(extra)
    else:
        wires[1]['ordinal'] = 1
    if reverse:
        clients.reverse()
        wires.reverse()
    joined = join_causal_trace(clients, wires, operation_id=op)
    assert joined['causal_join_complete'] is False
    assert audit(joined, AuditIntent(retryable_statuses=(503,)))['verdict'] == 'unknown'


def test_join_violation_survives_unrelated_malformed_inventory():
    op, clients, wires = streams()
    wires.append({'kind': 'arrival', 'operation_id': op, 'global_index': None})
    joined = join_causal_trace(clients, wires, operation_id=op)
    assert not joined['causal_join_complete']
    assert audit(joined, AuditIntent(retryable_statuses=(503,)))['verdict'] == 'mismatch'


@pytest.mark.parametrize('reverse', [False, True])
def test_conflicting_physical_identity_does_not_choose_first_arrival(reverse):
    op, clients, wires = streams()
    extra = deepcopy(wires[1])
    extra['ordinal'] = 1
    wires.append(extra)  # Same physical id, conflicting contents, not log replay.
    if reverse:
        wires.reverse()
    joined = join_causal_trace(clients, wires, operation_id=op)
    assert not joined['arrival_stream_complete']
    assert joined['wire_attempts_observed'] == 2
    assert audit(joined, AuditIntent(retryable_statuses=(503,)))['verdict'] == 'unknown'


@pytest.mark.parametrize('side', ['client', 'wire'])
def test_third_duplicate_cannot_restore_ambiguous_identity(side):
    op, clients, wires = streams()
    rows = clients if side == 'client' else wires
    original = deepcopy(rows[1])
    for n in (3, 4):
        extra = deepcopy(original)
        if side == 'wire':
            extra['global_index'] = n
        rows.append(extra)
    joined = join_causal_trace(clients, wires, operation_id=op)
    assert not joined['causal_join_complete']
    assert audit(joined, AuditIntent(retryable_statuses=(503,)))['verdict'] == 'unknown'


def test_other_dimensions_and_migration_do_not_depend_on_classification_completeness():
    before = trace(status=503)
    after = trace()
    after['arrivals'].append({'id': None, 'role': 'unknown'})
    for r in (before, after):
        r.update(wire_attempts_observed=3, arrival_stream_complete=False,
                 outcome='success', payload='ok', payload_complete=True,
                 body_elapsed_s=None, body_complete=False)
    intent = AuditIntent(max_wire_attempts=2, retryable_statuses=(503,),
                         required_outcome='success', expected_payload='ok', budget_s=.1)
    result = compare_migration(before, after, intent)
    assert {key: row['verdict'] for key, row in result['after']['dimensions'].items()} == {
        'attempts': 'mismatch', 'outcome': 'pass', 'payload': 'pass',
        'classification': 'mismatch', 'time': 'unknown',
    }
    assert result['after']['verdict'] == 'mismatch'
    assert result['dimension_transitions']['classification']['after'] == 'mismatch'


@pytest.mark.parametrize('arrivals,expected', [(None, 'unknown'), ([], 'pass'), ('bad', 'unknown')])
def test_empty_and_absent_inventories(arrivals, expected):
    r = {'arrivals': arrivals, 'arrival_stream_complete': True, 'retry_attribution_complete': True}
    assert audit(r, AuditIntent(retryable_statuses=(503,)))['verdict'] == expected
