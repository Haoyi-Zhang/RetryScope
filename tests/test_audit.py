import itertools
import pytest
from retryscope.audit import AuditIntent, audit, combine, from_legacy

def trace():
    return dict(arrivals=[{'id':1,'role':'initial','attribution_witness':'caller-entry'}], arrival_stream_complete=True,
        retry_attribution_complete=True, outcome='success',payload='abc',payload_complete=True,
        body_elapsed_s=.03,body_complete=True,headers_elapsed_s=.01,headers_complete=True,
        cleanup_elapsed_s=.04,cleanup_complete=True,admissions_s=[0.],admissions_complete=True)

@pytest.mark.parametrize('states',list(itertools.product(['pass','unknown','mismatch'],repeat=4)))
def test_conjunction_truth_table(states):
    expected='mismatch' if 'mismatch' in states else 'unknown' if 'unknown' in states else 'pass'
    assert combine(list(states))==expected

@pytest.mark.parametrize('bad',[None, float('nan'),float('inf'),-.01,True,'0.01'])
def test_bad_time_abstains(bad):
    r=trace();r['body_elapsed_s']=bad
    assert audit(r,AuditIntent(budget_s=.1))['verdict']=='unknown'

@pytest.mark.parametrize('field',['arrivals','outcome','payload','body_elapsed_s'])
def test_missing_requested_evidence_is_not_pass(field):
    r=trace();r.pop(field)
    intents={'arrivals':AuditIntent(max_wire_attempts=2),'outcome':AuditIntent(required_outcome='success'),
        'payload':AuditIntent(expected_payload='abc'),'body_elapsed_s':AuditIntent(budget_s=.1)}
    assert audit(r,intents[field])['verdict']=='unknown'

def test_fail_survives_unknown_dimension():
    r=trace();r['arrivals'] += [{'id':2}];r.pop('body_elapsed_s')
    v=audit(r,AuditIntent(max_wire_attempts=1,budget_s=.1))
    assert v['verdict']=='mismatch' and v['dimensions']['time']['verdict']=='unknown'

def test_prefix_count_can_disprove_but_not_prove():
    r=trace();r['arrival_stream_complete']=False
    assert audit(r,AuditIntent(max_wire_attempts=1))['verdict']=='unknown'
    r['arrivals'] += [{'id':2}]
    assert audit(r,AuditIntent(max_wire_attempts=1))['verdict']=='mismatch'

def test_no_status_adjacency_inference():
    r=trace();r['arrivals'] += [{'id':2,'role':'constituent','attribution_witness':'second user read'}]
    assert audit(r,AuditIntent(retryable_statuses=(503,)))['verdict']=='pass'
    r['arrivals'][1].pop('attribution_witness')
    assert audit(r,AuditIntent(retryable_statuses=(503,)))['verdict']=='unknown'

@pytest.mark.parametrize('kind,allow,expected',[('body_error',True,'pass'),('body_error',False,'mismatch'),('transport_error',True,'pass'),('transport_error',False,'mismatch'),('planned_status',True,'unknown')])
def test_retry_cause(kind,allow,expected):
    r=trace();r['arrivals'].append({'id':2,'role':'retry','owner':'caller','retry_of':1,'cause':{'kind':kind},'attribution_witness':'caller exception'})
    v=audit(r,AuditIntent(retryable_statuses=(503,),allow_body_recovery=allow,allow_transport_retry=allow))
    assert v['verdict']==expected

@pytest.mark.parametrize('status,expected',[(503,'pass'),(400,'mismatch'),(None,'unknown'),(True,'unknown'),(999,'unknown')])
def test_received_status(status,expected):
    r=trace();r['arrivals'].append({'id':2,'role':'retry','owner':'caller','retry_of':1,'cause':{'kind':'status','received_status':status},'attribution_witness':'response hook'})
    assert audit(r,AuditIntent(retryable_statuses=(503,)))['verdict']==expected

def test_arrival_not_admission():
    r={'arrivals':[{'id':1,'t':0},{'id':2,'t':.3}],'arrival_stream_complete':True}
    assert audit(r,AuditIntent(time_scope='admission',budget_s=.1))['verdict']=='unknown'

def test_boundaries_differ():
    r=trace();r['cleanup_elapsed_s']=.4
    assert audit(r,AuditIntent(boundary='body',budget_s=.1))['verdict']=='pass'
    assert audit(r,AuditIntent(boundary='cleanup',budget_s=.1))['verdict']=='mismatch'

@pytest.mark.parametrize('cap',[True,1.5,0,17])
def test_invalid_cap(cap):
    with pytest.raises(ValueError): AuditIntent(max_wire_attempts=cap)

def test_empty_intent_unknown():
    assert audit(trace(),AuditIntent())['verdict']=='unknown'

def test_legacy_causes_not_fabricated():
    r=from_legacy({'events':[{'kind':'arrival','index':1,'status':503}], 'trace_complete':True})
    assert audit(r,AuditIntent(retryable_statuses=(503,)))['verdict']=='unknown'
