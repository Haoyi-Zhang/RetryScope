import time

from retryscope.observation import RetryObserver, build_trace, exception_cause, make_observed_retry


def base_record():
    return {
        'config': {'mode': 'body'},
        'events': [
            {'kind':'arrival','index':1,'t':1.0},
            {'kind':'arrival','index':2,'t':2.0},
        ],
        'client_events': [
            {'kind':'attempt_result','source':'sdk','cause':{'kind':'status','received_status':503},'t':1.5},
        ],
        'trace_complete': True,
        'outcome':'success','payload':'ok','elapsed_s':.2,'headers_elapsed_s':.01,
    }


def test_build_trace_uses_client_cause():
    trace=build_trace(base_record())
    assert trace['retry_attribution_complete'] is True
    assert trace['arrivals'][1]['role']=='retry'
    assert trace['arrivals'][1]['cause']['received_status']==503
    assert trace['arrivals'][1]['owner']=='sdk'


def test_missing_client_cause_abstains():
    record=base_record();record['client_events']=[]
    trace=build_trace(record)
    assert trace['retry_attribution_complete'] is False
    assert trace['arrivals'][1]['role']=='unknown'


def test_latest_body_error_wins_over_success_headers():
    record=base_record();record['client_events']=[
        {'kind':'attempt_result','source':'sdk','cause':{'kind':'status','received_status':200},'t':1.2},
        {'kind':'body_error','source':'stream','cause':{'kind':'body_error','exception':'IncompleteRead'},'t':1.8},
    ]
    trace=build_trace(record)
    assert trace['arrivals'][1]['cause']['kind']=='body_error'
    assert trace['arrivals'][1]['owner']=='stream'


def test_exception_cause_distinguishes_body_and_transport():
    class IncompleteRead(Exception): pass
    class ConnectTimeout(Exception): pass
    assert exception_cause(IncompleteRead())['kind']=='body_error'
    assert exception_cause(ConnectTimeout())['kind']=='transport_error'


def test_observed_retry_records_only_scheduled_retry():
    import urllib3
    observer=RetryObserver()
    retry=make_observed_retry(urllib3.util.Retry,observer,source='test',total=1,status_forcelist=[503],allowed_methods=['GET'])
    class Response:
        status=503
        def get_redirect_location(self): return False
        headers={}
    new=retry.increment('GET','http://local',response=Response())
    assert new is not retry
    assert observer.events[-1]['kind']=='retry_start'
    assert observer.events[-1]['cause']=={'kind':'status','received_status':503}


def test_explicit_retry_start_has_priority_over_later_generic_result():
    record=base_record();record['client_events']=[
        {'kind':'retry_start','source':'owner','cause':{'kind':'status','received_status':503},'t':1.4},
        {'kind':'attempt_result','source':'hook','cause':{'kind':'status','received_status':200},'t':1.9},
    ]
    trace=build_trace(record)
    assert trace['arrivals'][1]['owner']=='owner'
    assert trace['arrivals'][1]['cause']['received_status']==503


def test_observed_sleep_records_retry_admission_without_global_sleep():
    from retryscope.observed_worker import _ObservedSleepModule
    class FakeTime:
        def __init__(self): self.sleeps=[]
        def sleep(self, seconds): self.sleeps.append(seconds)
    observer=RetryObserver()
    observer.response(503, source='client')
    fake=FakeTime()
    proxy=_ObservedSleepModule(fake, observer, 'retry-owner')
    proxy.sleep(.25)
    assert fake.sleeps == [.25]
    assert observer.events[-1]['kind']=='retry_start'
    assert observer.events[-1]['source']=='retry-owner'
    assert observer.events[-1]['cause']=={'kind':'status','received_status':503}
