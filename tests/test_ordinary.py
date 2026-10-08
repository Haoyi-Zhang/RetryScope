from types import SimpleNamespace
import pytest
from retryscope.ordinary import checked_identity_body, total_attempt_config

class Incomplete(Exception): pass

def response(body=b'0123456789', headers=None):
    return SimpleNamespace(content=body, headers={'Content-Length':'10'} if headers is None else headers,
                           raise_for_status=lambda:None)

def test_complete_identity():
    assert checked_identity_body(response(), Incomplete)==b'0123456789'
def test_short_identity():
    with pytest.raises(Incomplete): checked_identity_body(response(b'01'), Incomplete)
@pytest.mark.parametrize('headers', [{},{'Content-Length':'abc'}, {'Content-Length':'-1'},
    {'Content-Length':'10','Content-Encoding':'gzip'}])
def test_unsupported_framing(headers):
    with pytest.raises(ValueError): checked_identity_body(response(headers=headers), Incomplete)
def test_http_error_preserved():
    r=response()
    def fail(): raise RuntimeError('status error')
    r.raise_for_status=fail
    with pytest.raises(RuntimeError,match='status error'): checked_identity_body(r,Incomplete)
@pytest.mark.parametrize('n',[True,False,0,-1,17,2.5,'2',None])
def test_bad_total(n):
    with pytest.raises(ValueError): total_attempt_config(n)
@pytest.mark.parametrize('n',[1,2,16])
def test_good_total(n):
    assert total_attempt_config(n).retries=={'mode':'standard','total_max_attempts':n}
