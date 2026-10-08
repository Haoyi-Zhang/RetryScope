import json
from retryscope.cli import main
import pytest

def run(tmp_path,r,i,**kw):
    t=tmp_path/'trace.json';c=tmp_path/'intent.json';o=tmp_path/'output.json'
    t.write_text(json.dumps(r));c.write_text(json.dumps(i))
    return main(['--trace',str(t),'--intent',str(c),'--output',str(o)]),o

def test_pass(tmp_path):
    code,o=run(tmp_path,{'arrivals':[{'id':1}],'arrival_stream_complete':True},{'max_wire_attempts':1})
    assert code==0 and json.loads(o.read_text())['verdict']=='pass'
def test_unknown(tmp_path):assert run(tmp_path,{}, {'max_wire_attempts':1})[0]==2
def test_mismatch(tmp_path):assert run(tmp_path,{'arrivals':[{'id':1},{'id':2}]},{'max_wire_attempts':1})[0]==1
@pytest.mark.parametrize('r',[[],{'arrivals':'bad'},{'arrivals':[None]},{'arrivals':[{'id':1,'cause':None}]},{'arrivals':[{'id':1,'retry_of':True}]},{'arrivals':[{'id':1,'role':'guess'}]},{'body_elapsed_s':float('nan')},{'body_elapsed_s':-1},{'arrival_stream_complete':'yes'}])
def test_bad_trace(tmp_path,r):assert run(tmp_path,r,{'max_wire_attempts':1})[0]==3
@pytest.mark.parametrize('i',[[],{'max_wire_attempts':True},{'budget_s':float('inf')},{'unexpected':1}])
def test_bad_intent(tmp_path,i):assert run(tmp_path,{},i)[0]==3
def test_duplicate_field(tmp_path):
    t=tmp_path/'t';i=tmp_path/'i';t.write_text('{"outcome":"success","outcome":"error"}');i.write_text('{}')
    assert main(['--trace',str(t),'--intent',str(i)])==3


def test_paired_comparison_uses_evidence_aware_category(tmp_path):
    before=tmp_path/'before.json';after=tmp_path/'after.json';intent=tmp_path/'intent.json';out=tmp_path/'out.json'
    before.write_text(json.dumps({'arrivals':[{'id':1}],'arrival_stream_complete':True}))
    after.write_text(json.dumps({'arrivals':[{'id':1}],'arrival_stream_complete':False}))
    intent.write_text(json.dumps({'max_wire_attempts':1}))
    code=main(['--before',str(before),'--trace',str(after),'--intent',str(intent),'--output',str(out)])
    result=json.loads(out.read_text())
    assert code==2
    assert result['category']=='evidence_loss'
    assert result['before']['verdict']=='pass' and result['after']['verdict']=='unknown'


def test_paired_comparison_repair_exit_code_tracks_after(tmp_path):
    before=tmp_path/'before.json';after=tmp_path/'after.json';intent=tmp_path/'intent.json';out=tmp_path/'out.json'
    before.write_text(json.dumps({'arrivals':[{'id':1},{'id':2}],'arrival_stream_complete':True}))
    after.write_text(json.dumps({'arrivals':[{'id':1}],'arrival_stream_complete':True}))
    intent.write_text(json.dumps({'max_wire_attempts':1}))
    code=main(['--before',str(before),'--trace',str(after),'--intent',str(intent),'--output',str(out)])
    result=json.loads(out.read_text())
    assert code==0 and result['category']=='repair'
