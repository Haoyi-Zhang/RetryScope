import pytest
from retryscope.checker import Intent, check, compare
from retryscope.responder import Reply, Responder

def trace(statuses=(503, 200), elapsed=0.05, payload='0123456789', outcome='success', **kw):
    return dict(trace_complete=True, start_t=10.0, elapsed_s=elapsed, headers_elapsed_s=0.001,
                outcome=outcome, payload=payload,
                events=[dict(kind='arrival',t=10+i*0.02,index=i+1,status=s) for i,s in enumerate(statuses)], **kw)

def test_attempt_cap():
    assert check(trace(), Intent(max_wire_attempts=1))['findings'][0]['dimension']=='attempts'
def test_known_valid():
    assert check(trace(),Intent(max_wire_attempts=2,retryable_statuses=(503,)))['verdict']=='pass'
def test_abstention():
    assert check(trace(),Intent())['verdict']=='unknown'
def test_classification():
    assert check(trace((400,400)),Intent(retryable_statuses=(503,)))['findings'][0]['dimension']=='classification'
def test_body_boundary():
    r=trace((200,),elapsed=.3)
    assert check(r,Intent(budget_s=.1,time_scope='operation',boundary='headers'))['verdict']=='pass'
    assert check(r,Intent(budget_s=.1,time_scope='operation',boundary='body'))['verdict']=='mismatch'
def test_tolerance():
    assert check(trace(elapsed=.119),Intent(budget_s=.1,time_scope='operation'))['verdict']=='pass'
    assert check(trace(elapsed=.121),Intent(budget_s=.1,time_scope='operation'))['verdict']=='mismatch'
def test_admission_is_not_duration():
    assert check(trace(elapsed=.3),Intent(budget_s=.1,time_scope='admission'))['verdict']=='pass'
    r=trace();r['events'][1]['t']=10.13
    assert check(r,Intent(budget_s=.1,time_scope='admission'))['verdict']=='mismatch'
def test_incomplete_trace_unknown():
    r=trace();r['trace_complete']=False
    assert check(r,Intent(max_wire_attempts=1))['verdict']=='unknown'
def test_payload_contract():
    assert check(trace(payload='01'),Intent(expected_payload_on_success='0123456789'))['verdict']=='mismatch'
    assert check(trace(outcome='error',payload=None),Intent(expected_payload_on_success='0123456789'))['verdict']=='pass'
def test_required_recovery():
    assert check(trace(outcome='error'),Intent(required_outcome='success'))['verdict']=='mismatch'
def test_body_retry_permitted_only_explicitly():
    r=trace((200,200));r['events'][0]['body_fault']=True
    assert check(r,Intent(retryable_statuses=(503,)))['verdict']=='mismatch'
    assert check(r,Intent(retryable_statuses=(503,),allow_body_recovery=True))['verdict']=='pass'
@pytest.mark.parametrize('budget',[0,-1,float('inf'),float('nan')])
def test_bad_budget(budget):
    with pytest.raises(ValueError): Intent(budget_s=budget)
@pytest.mark.parametrize('cap',[0,-1,17])
def test_bad_cap(cap):
    with pytest.raises(ValueError): Intent(max_wire_attempts=cap)
def test_no_false_defect_attribution():
    r=compare(trace(),trace((503,503,503)),Intent(max_wire_attempts=2))
    assert r['transition']=='pass -> mismatch'
    assert 'not automatic' in r['interpretation']
def test_reply_bounds():
    with pytest.raises(ValueError): Reply(header_delay=2)
    with pytest.raises(ValueError): Reply(retry_after='100')
def test_loopback_server_real_http():
    import urllib.request
    with Responder([Reply(status=200)]) as s:
        assert s.url.startswith('http://127.0.0.1:')
        assert urllib.request.urlopen(s.url,timeout=1).read()==b'0123456789'
        assert s.quiesce()
        assert s.count==1
