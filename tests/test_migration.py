import pytest

from retryscope.audit import AuditIntent
from retryscope.migration import compare_migration, evidence_obligations, intent_fingerprint


def trace(*, n=1, payload='ok', complete=True, role='initial', cause=None, owner=None):
    rows=[]
    for i in range(1,n+1):
        row={'id':i,'role':role if i>1 else 'initial','attribution_witness':'test'}
        if i>1:
            row['retry_of']=i-1
            row['cause']=cause or {'kind':'status','received_status':503}
            if owner is not None:
                row['owner']=owner
        rows.append(row)
    return {
        'arrivals':rows,
        'arrival_stream_complete':complete,
        'retry_attribution_complete':complete,
        'outcome':'success',
        'payload':payload,
        'payload_complete':True,
        'body_elapsed_s':0.01,
        'body_complete':True,
        'cleanup_elapsed_s':0.02,
        'cleanup_complete':True,
    }


def test_repair_transition_and_changed_observation():
    intent=AuditIntent(max_wire_attempts=2,expected_payload='ok')
    result=compare_migration(trace(n=3),trace(n=2),intent,pair_id='p')
    assert result['category']=='repair'
    assert result['dimension_transitions']['attempts']['category']=='repair'
    assert result['behavior_changed']


def test_evidence_loss_is_not_regression():
    intent=AuditIntent(max_wire_attempts=2)
    result=compare_migration(trace(n=1),trace(n=1,complete=False),intent)
    assert result['category']=='evidence_loss'
    assert result['after']['verdict']=='unknown'


def test_stable_pass_can_still_change_behavior():
    intent=AuditIntent(max_wire_attempts=5)
    result=compare_migration(trace(n=5),trace(n=3),intent)
    assert result['category']=='stable_conformant'
    assert result['behavior_changed']
    assert result['changed_dimensions']==['attempts']


@pytest.mark.parametrize('allow,owner,verdict,category', [
    (True, 'object-validator', 'pass', 'stable_conformant'),
    (False, 'object-validator', 'mismatch', 'regression'),
    (True, None, 'unknown', 'evidence_loss'),
])
def test_integrity_retry_classification(allow,owner,verdict,category):
    intent=AuditIntent(retryable_statuses=(503,),allow_integrity_retry=allow)
    before=trace(n=1)
    after=trace(n=2,role='retry',owner=owner,cause={'kind':'content_mismatch'})
    result=compare_migration(before,after,intent)
    assert result['category']==category
    assert result['before']['verdict']=='pass'
    assert result['after']['verdict']==verdict
    classification=result['after']['dimensions']['classification']
    assert classification['verdict']==verdict
    assert classification['requests'][1]=={
        'id':2, 'verdict':verdict, 'role':'retry', 'owner':owner,
        'retry_of':1, 'cause':{'kind':'content_mismatch'},
    }
    transition=result['dimension_transitions']['classification']
    assert transition['before']=='pass' and transition['after']==verdict
    assert transition['category']==category


def test_obligations_and_fingerprint_stable():
    intent=AuditIntent(expected_payload='ok',budget_s=.1,boundary='cleanup')
    assert evidence_obligations(intent)=={
        'payload':['outcome','payload','payload_complete'],
        'time':['cleanup_elapsed_s','cleanup_complete'],
    }
    assert intent_fingerprint(intent)==intent_fingerprint(intent)


def test_unconstrained_constituent_count_is_reported_structurally():
    intent=AuditIntent(expected_payload='ok')
    before=trace(n=1)
    after=trace(n=4)
    result=compare_migration(before,after,intent)
    assert result['category']=='stable_conformant'
    assert result['structural_behavior_changed']
    assert result['structural_delta']['wire_attempts']=={'before':1,'after':4}
