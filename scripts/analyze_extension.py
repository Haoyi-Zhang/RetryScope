#!/usr/bin/env python3
"""Verify frozen executions and regenerate evidence-aware metrics and plots."""
from __future__ import annotations
import argparse, collections, copy, csv, hashlib, json, statistics, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from retryscope.audit import AuditIntent,audit,from_legacy
from retryscope.checker import Intent,check
from retryscope.range_fixture import PAYLOAD

def load(p):return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write_csv(p,rs):
    with p.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rs[0]));w.writeheader();w.writerows(rs)
def q(xs,p):
    xs=sorted(xs);i=(len(xs)-1)*p;k=int(i);return xs[k]+(xs[min(k+1,len(xs)-1)]-xs[k])*(i-k)
def evidence_intent(r):
    d=Intent(**r['config']['intent']).to_dict();d['expected_payload']=d.pop('expected_payload_on_success')
    if d['time_scope']=='observation':d['time_scope']='operation';d['budget_s']=None
    return AuditIntent(**d)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,default=ROOT/'results/extension-derived');ap.add_argument('--paper-dir',type=Path);ap.add_argument('--raw',type=Path,default=ROOT/'results/raw/extension');ap.add_argument('--legacy-raw',type=Path,default=ROOT/'results/raw/evaluation');a=ap.parse_args();a.out.mkdir(exist_ok=True,parents=True)
    raw=a.raw;freeze=json.loads((raw/'freeze.json').read_text())
    frozen_relocations = {
        'scripts/extend_study.py': ROOT/'evidence/source-snapshots/frozen-extension-runner.py',
        'src/retryscope/audit.py': ROOT/'evidence/source-snapshots/frozen-extension-audit.py',
        'src/retryscope/range_fixture.py': ROOT/'evidence/source-snapshots/frozen-range-fixture.py',
        'study/extension-protocol.md': ROOT/'evidence/source-snapshots/frozen-extension-protocol.md',
    }
    for rel,digest in freeze['sources'].items():
        source = ROOT/rel
        if sha(source) != digest and rel in frozen_relocations:
            source = frozen_relocations[rel]
        assert sha(source)==digest,rel
    rs=load(raw/'records.jsonl');expected={(c['id'],s) for c in freeze['cases'] for s in freeze['seeds']}
    assert len(rs)==len(expected)==402 and {(r['id'],r['seed']) for r in rs}==expected
    ci=AuditIntent(expected_payload=PAYLOAD.decode(),provenance='registered object identity (Pooch); explicit same-object probe for other readers')
    for r in rs:
        assert not r.get('harness_error'),r['id']
        assert r['arrival_stream_complete'] and r['body_complete'] and 1<=r['wire_attempts']<=16,r['id']
        assert r['wire_attempts']==len(r['arrivals'])==sum(e['kind']=='arrival' for e in r['events']),r['id']
        assert audit(r,ci)==r['content_audit'],r['id']
        cap=1 if r['case']['mode'].endswith('0') else 2
        ri=AuditIntent(max_wire_attempts=cap if r['case']['family']=='download' else None,retryable_statuses=(503,),allow_body_recovery=True,allow_transport_retry=True,provenance='local selective-retry probe; not a documented Pooch 400 exclusion')
        assert audit(r,ri)==r['retry_audit'],r['id']
        assert all(e.get('method','GET') in ('GET','HEAD') for e in r['events'])
    groups=collections.defaultdict(list)
    for r in rs:groups[r['id']].append(r)
    rows=[]
    for key,rr in sorted(groups.items()):
        ts=[r['body_elapsed_s']*1000 for r in rr]
        rows.append(dict(id=key,n=len(rr),family=rr[0]['case']['family'],mode=rr[0]['case'].get('mode','range'),scenario=rr[0]['case'].get('scenario','healthy'),success=sum(r['outcome']=='success' for r in rr),wrong_success=sum(r['outcome']=='success' and r['payload']!=PAYLOAD.decode() for r in rr),content_mismatch=sum(r['content_audit']['verdict']=='mismatch' for r in rr),retry_mismatch=sum(r['retry_audit']['verdict']=='mismatch' for r in rr),retry_unknown=sum(r['retry_audit']['verdict']=='unknown' for r in rr),wire_min=min(r['wire_attempts'] for r in rr),wire_max=max(r['wire_attempts'] for r in rr),min_ms=min(ts),median_ms=statistics.median(ts),max_ms=max(ts)))
    write_csv(a.out/'cells.csv',rows)
    summary=dict(records=len(rs),cells=len(groups),replicates=6,wire_attempts=sum(r['wire_attempts'] for r in rs),max_wire_attempts=max(r['wire_attempts'] for r in rs),operation_seconds=sum(r['body_elapsed_s'] for r in rs),content_verdicts=dict(collections.Counter(r['content_audit']['verdict'] for r in rs)),retry_verdicts=dict(collections.Counter(r['retry_audit']['verdict'] for r in rs)),raw_sha256=sha(raw/'records.jsonl'),families={})
    for f in sorted({r['case']['family'] for r in rs}):
        rr=[r for r in rs if r['case']['family']==f]
        summary['families'][f]=dict(n=len(rr),wire_attempts=sum(r['wire_attempts'] for r in rr),outcomes=dict(collections.Counter(r['outcome'] for r in rr)),content=dict(collections.Counter(r['content_audit']['verdict'] for r in rr)),retry=dict(collections.Counter(r['retry_audit']['verdict'] for r in rr)))
    # Legacy labels are retained, while a separate current re-audit abstains on unobserved ownership.
    legacy=[r for p in sorted(a.legacy_raw.glob('*.jsonl')) for r in load(p)]
    assert len(legacy)==1068
    transitions=collections.Counter();dims=collections.Counter();re=[]
    for r in legacy:
        current=audit(from_legacy(r),evidence_intent(r));transitions[r['check']['verdict']+' -> '+current['verdict']]+=1
        dims.update(d+':'+v['verdict'] for d,v in current['dimensions'].items())
        re.append(dict(id=r['id'],seed=r['seed'],archived=r['check']['verdict'],current=current))
    (a.out/'legacy-reaudit.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in re))
    summary['legacy_reaudit']={'n':len(re),'verdicts':dict(collections.Counter(r['current']['verdict'] for r in re)),'transitions':dict(transitions),'dimensions':dict(dims)}
    # Explicit observation ablations: replay facts, not additional library executions.
    ablations=[]
    for r in rs:
        if r['outcome']!='success':continue
        incomplete=copy.deepcopy(r);incomplete['payload_complete']=False
        missing=copy.deepcopy(r);missing.pop('payload',None)
        base_trace={'trace_complete':True,'outcome':r['outcome'],'payload':r['payload'],'events':[]}
        iv1=Intent(expected_payload_on_success=PAYLOAD.decode())
        for mode,x in [('complete',r),('unwitnessed_body',incomplete),('missing_payload',missing)]:
            old=copy.deepcopy(base_trace)
            if mode=='missing_payload':old.pop('payload',None)
            v=audit(x,ci)['verdict'];ablations.append(dict(id=r['id'],seed=r['seed'],mode=mode,baseline_payload_verdict=check(old,iv1)['verdict'],evidence_payload_verdict=v))
    write_csv(a.out/'observation-ablations.csv',ablations)
    summary['ablations']={mode:dict(collections.Counter(r['evidence_payload_verdict'] for r in ablations if r['mode']==mode)) for mode in ['complete','unwitnessed_body','missing_payload']}
    # Deliberately restricted adjacent-arrival baseline against witnessed healthy constituent requests.
    naive=[]
    for r in rs:
        if r['case']['family']!='constituent_reads':continue
        old={'trace_complete':True,'events':[dict(kind='arrival',index=e['id'],t=e['t'],status=e['status']) for e in r['arrivals']]}
        v=check(old,Intent(retryable_statuses=(503,)))
        naive.append(dict(id=r['id'],seed=r['seed'],wire=r['wire_attempts'],adjacent_baseline=v['verdict'],attributed_verdict=r['retry_audit']['verdict']))
    write_csv(a.out/'constituent-control.csv',naive)
    summary['adjacent_control']={'n':len(naive),'false_alarms':sum(r['adjacent_baseline']=='mismatch' for r in naive),'attributed_false_alarms':sum(r['attributed_verdict']=='mismatch' for r in naive)}
    # Machine-time measurement is an offline replay cost, not a production-overhead estimate.
    bp=a.out/'offline-benchmark.json'
    if not bp.exists():
        timings=[]
        for _ in range(20):
            t=time.perf_counter_ns()
            for r in rs:audit(r,ci)
            timings.append((time.perf_counter_ns()-t)/1e6)
        bp.write_text(json.dumps({'records_per_pass':402,'raw_sha256':summary['raw_sha256'],'source_sha256':sha(ROOT/'src/retryscope/audit.py'),'milliseconds':timings},indent=2)+'\n')
    benchmark=json.loads(bp.read_text());assert benchmark['raw_sha256']==summary['raw_sha256'];summary['offline_median_ms']=statistics.median(benchmark['milliseconds'])
    (a.out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    # Outcomes encode correctness as well as liveness; errors do not count as successful recovery.
    modes=['pooch_hash0','pooch_hash1','pooch_unchecked1','requests_old_length','requests_new_length','requests_old_hash','requests_new_hash']
    labels=['Pooch hash, 0 retries','Pooch hash, 1 retry','Pooch unchecked, 1 retry','Old Requests + length','New Requests + length','Old Requests + hash','New Requests + hash']
    scs=['success','transient','persistent','denied','truncated_once','corrupt_once','corrupt_always'];byid={r['id']:r for r in rows}
    table=[]
    for m,label in zip(modes,labels):
        cells=[]
        for sc in scs:
            row=byid[m+'_'+sc];assert row['wire_min']==row['wire_max'];n=row['wire_min']
            outcome='W' if row['wrong_success']==6 else ('C' if row['success']==6 else 'E');cells.append(outcome+str(n))
        table.append(label+' & '+' & '.join(cells)+r' \\')
    (a.out/'download-rows.tex').write_text('\n'.join(table)+'\n')
    rr=[r for r in rs if r['case']['family']=='range_recovery'];rangerows=[]
    for size in (3,11,23):
        for cut in (7,31,63):
            sub=[r for r in rr if r['case']['read_size']==size and r['case'].get('cut')==cut and r['case']['scenario']=='truncated_once']
            # Arrival offsets, not assumed cut positions: unread buffer contents can change restart location.
            offsets=sorted({r['arrivals'][1]['start'] for r in sub})
            rangerows.append(dict(read_size=size,cut=cut,n=len(sub),second_request_offsets=','.join(map(str,offsets)),all_correct=all(r['payload']==PAYLOAD.decode() for r in sub)))
    write_csv(a.out/'range-offsets.csv',rangerows)
    import matplotlib
    matplotlib.use('Agg');matplotlib.rcParams['pdf.fonttype']=42;matplotlib.rcParams['ps.fonttype']=42
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(3.48,2.45))
    for i,(m,label) in enumerate(zip(modes,labels)):
        sub=[r for r in rs if r['case'].get('mode')==m and r['case']['scenario']=='corrupt_once']
        vals=[r['body_elapsed_s']*1000 for r in sub]
        ax.scatter(vals,[i]*len(vals),s=17,alpha=.7)
        ax.plot([statistics.median(vals)],[i],marker='|',markersize=13)
    ax.set_xscale('log');ax.set_yticks(range(len(labels)),labels);ax.set_xlabel('Complete operation, including setup (ms)');ax.grid(axis='x',alpha=.2);fig.tight_layout()
    fig.savefig(a.out/'identity-time.pdf');fig.savefig(a.out/'identity-time.svg');plt.close(fig)
    fig,ax=plt.subplots(figsize=(3.48,2.35))
    for mode,label in [('known_size','Size supplied'),('metadata','Metadata discovery')]:
        xy=[(size,byid[f'fsspec_{mode}_{size}']['wire_min']) for size in (8,17,31)];ax.plot(*zip(*xy),marker='o',label=label)
    ax.set_xlabel('Caller read size (bytes)');ax.set_ylabel('Wire requests for 96 bytes');ax.legend(frameon=False);ax.set_ylim(0,16);ax.set_xticks([8,17,31]);ax.grid(alpha=.2);fig.tight_layout()
    fig.savefig(a.out/'constituent-count.pdf');fig.savefig(a.out/'constituent-count.svg');plt.close(fig)
    if a.paper_dir:
        import shutil
        for d in ('generated','figures'):(a.paper_dir/d).mkdir(exist_ok=True,parents=True)
        for p in a.out.glob('*.tex'):shutil.copy2(p,a.paper_dir/'generated'/p.name)
        for ext in ('pdf','svg'):
            for p in a.out.glob('*.'+ext):shutil.copy2(p,a.paper_dir/'figures'/p.name)
    print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
