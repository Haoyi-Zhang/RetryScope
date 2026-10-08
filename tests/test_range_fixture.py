import requests,pytest
from retryscope.range_fixture import RangeFixture,PAYLOAD

@pytest.mark.parametrize('lo,hi',[(0,0),(0,95),(7,31),(11,22),(31,63),(63,95)])
def test_byte_ranges(lo,hi):
    with RangeFixture() as f,requests.Session() as s:
        s.trust_env=False;r=s.get(f.url+'/data',headers={'Range':f'bytes={lo}-{hi}'},timeout=1)
        assert r.status_code==206 and r.content==PAYLOAD[lo:hi+1]
        assert r.headers['Content-Range']==f'bytes {lo}-{hi}/96'
        assert int(r.headers['Content-Length'])==hi-lo+1

def test_head():
    with RangeFixture() as f,requests.Session() as s:
        s.trust_env=False;r=s.head(f.url,timeout=1);assert not r.content and int(r.headers['Content-Length'])==96

def test_declared_corruption_is_not_a_length_error():
    with RangeFixture('corrupt_once') as f,requests.Session() as s:
        s.trust_env=False;r=s.get(f.url,timeout=1);assert len(r.content)==96 and r.content!=PAYLOAD
        assert s.get(f.url,timeout=1).content==PAYLOAD
@pytest.mark.parametrize('kw',[{'cap':0},{'cap':17},{'payload':b''},{'payload':b'x'*4097},{'cut':100},{'scenario':'unsupported'}])
def test_bad_fixture(kw):
    with pytest.raises(ValueError):RangeFixture(**kw)
