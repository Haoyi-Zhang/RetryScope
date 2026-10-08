#!/usr/bin/env python3
"""Regenerate tables and vector plots from actual JSONL traces, without network."""
from __future__ import annotations
from pathlib import Path
import argparse, csv, json, statistics, collections, sys, time, hashlib
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from retryscope.checker import Intent, check

def quantiles(xs):
 xs=sorted(xs)
 def q(p):
  pos=(len(xs)-1)*p;i=int(pos);return xs[i]+(xs[min(i+1,len(xs)-1)]-xs[i])*(pos-i)
 return [min(xs),q(.25),q(.5),q(.75),max(xs)]

def load(paths):
 return [json.loads(line) for p in paths for line in p.read_text().splitlines() if line.strip()]

def write_csv(path,rows):
 if not rows:return
 with path.open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def main():
 a=argparse.ArgumentParser();a.add_argument('--raw',type=Path,default=ROOT/'results/raw/evaluation')
 a.add_argument('--out',type=Path,default=ROOT/'results/derived');a.add_argument('--paper-dir',type=Path)
 args=a.parse_args();out=args.out;out.mkdir(parents=True,exist_ok=True)
 paths=sorted(args.raw.glob('*.jsonl'));rs=load(paths)
 if not rs:raise SystemExit('No raw records found')
 configs=json.loads((ROOT/'study/cases.json').read_text())
 expected_ids={c['id'] for c in configs}
 got={(r['id'],r['seed']) for r in rs}
 expected={(i,s) for i in expected_ids for s in range(101,113)}
 if got!=expected or len(rs)!=len(got):raise SystemExit(f'Incomplete/duplicate study: {len(rs)} records, missing {len(expected-got)}')
 for r in rs:
  assert not r.get('harness_error'),r
  assert r['trace_complete'] and r['wire_attempts']<=16,r['id']
  assert len([e for e in r['events'] if e['kind']=='arrival'])==r['wire_attempts']
  assert all(e.get('method','GET') in ('GET','HEAD') for e in r['events'])
  assert r['check']==check(r,Intent(**r['config']['intent'])),r['id']
 groups=collections.defaultdict(list)
 for r in rs:groups[r['id']].append(r)
 rows=[]
 for id,rr in sorted(groups.items()):
  q=quantiles([r['elapsed_s']*1000 for r in rr])
  rows.append(dict(id=id,n=len(rr),stack=rr[0]['config']['stack'],scenario=rr[0]['config']['scenario'],
    wire_min=min(r['wire_attempts'] for r in rr),wire_max=max(r['wire_attempts'] for r in rr),
    success=sum(r.get('outcome')=='success' for r in rr),
    mismatch=sum(r['check']['verdict']=='mismatch' for r in rr),unknown=sum(r['check']['verdict']=='unknown' for r in rr),
    min_ms=q[0],q1_ms=q[1],median_ms=q[2],q3_ms=q[3],max_ms=q[4],
    exceptions=';'.join(sorted({r.get('exception','none') for r in rr})),
    payloads=';'.join(sorted({str(r.get('payload')) for r in rr}))))
 write_csv(out/'cell-summary.csv',rows)
 byid={r['id']:r for r in rows}
 dims=collections.Counter(f['dimension'] for r in rs for f in r['check']['findings'])
 # Counts of records, rather than multiple findings within a record.
 dims_record={d:sum(any(f['dimension']==d for f in r['check']['findings']) for r in rs) for d in dims}
 controls=[r for r in rs if r['config']['scenario'] in ('success','metadata')]
 declared_boto=[r for r in rs if r['id'].startswith(('boto_false_','boto_true_'))]
 raw_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
 benchmark_path=out/'offline-check-benchmark.json'
 if benchmark_path.exists():
  benchmark=json.loads(benchmark_path.read_text())
  if benchmark['raw_sha256']!=raw_hashes:
   raise SystemExit('Benchmark inputs changed; use a fresh analysis output directory')
  check_times=benchmark['ten_passes_ms']
 else:
  check_times=[]
  for _ in range(10):
   t=time.perf_counter_ns()
   for r in rs:check(r,Intent(**r['config']['intent']))
   check_times.append((time.perf_counter_ns()-t)/1e6)
  import datetime,platform
  benchmark_path.write_text(json.dumps(dict(utc=datetime.datetime.now(datetime.UTC).isoformat(),
      platform=platform.platform(),python=sys.version,raw_sha256=raw_hashes,
      records_per_pass=len(rs),ten_passes_ms=check_times),indent=2)+'\n')
 summary=dict(records=len(rs),cells=len(groups),replicates=12,
    wire_attempts=sum(r['wire_attempts'] for r in rs),maximum_wire_attempts=max(r['wire_attempts'] for r in rs),
    verdicts=dict(collections.Counter(r['check']['verdict'] for r in rs)),dimensions=dims_record,
    operation_machine_seconds=sum(r['elapsed_s'] for r in rs),
    setup_seconds=sum(r['setup_s'] for r in rs),
    success_control_records=len(controls),success_control_alarms=sum(r['check']['verdict']!='pass' for r in controls),
    source_boto_controls=len(declared_boto),source_boto_control_alarms=sum(r['check']['verdict']!='pass' for r in declared_boto),
    offline_check_ms=quantiles(check_times),
    raw_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
 (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
 # Raw rows with relative event times make the observation boundary inspectable.
 event_rows=[]
 for r in rs:
  for e in r['events']:
   event_rows.append(dict(id=r['id'],seed=r['seed'],kind=e['kind'],attempt=e.get('index'),
      relative_ms=(e['t']-r['start_t'])*1000,status=e.get('status'),bytes=e.get('bytes')))
 write_csv(out/'event-timeline.csv',event_rows)
 def line(label,id):
  r=byid[id];return f"{label} & {r['wire_min']} & {r['success']}/{r['n']} & {r['median_ms']:.1f} & [{r['min_ms']:.1f}, {r['max_ms']:.1f}] \\\\"
 boto=[('Pre-policy default','boto_false_default'),('2026 default','boto_true_default'),
       ('Pre-policy explicit standard','boto_false_explicit_standard'),('2026 explicit standard','boto_true_explicit_standard'),
       ('2026 Config max=2','boto_true_max2'),('2026 Config total=2','boto_true_total2')]
 (out/'boto-rows.tex').write_text('\n'.join(line(label,id) for label,id in boto)+'\n')
 deadline=[('Requests inactivity','req_native_trickle'),('Requests stop-delay','req_stop_delay_trickle'),
    ('Requests admission','req_admission_trickle'),('Context-managed future','req_future_timeout_trickle'),
    ('Boto body consumed','boto_trickle_body'),('Boto headers only','boto_trickle_headers_only'),
    ('urllib3 1.26.20 total','urllib3_old_trickle'),('urllib3 2.7.0 total','urllib3_new_trickle'),
    (r'smart\_open S3','smart_trickle'),('Hub backoff normalized','hf_normalized_trickle'),
    ('Requests delayed headers','req_native_slow_headers')]
 (out/'deadline-rows.tex').write_text('\n'.join(line(label,id) for label,id in deadline)+'\n')
 baseline=[]
 for name,mode in [('Native retry count','native'),('Count normalized','normalized'),('Broad outer retry','outer_broad'),('Restricted outer retry','outer_selective'),('Body-aware outer retry','body_aware'),('Admission guard','admission')]:
  rr=[byid[f'req_{mode}_{sc}'] for sc in ('success','transient','persistent','denied')]
  baseline.append(f"{name} & {'/'.join(str(r['wire_min']) for r in rr)} & {sum(r['mismatch'] for r in rr)}/{sum(r['n'] for r in rr)} \\\\ ")
 (out/'baseline-rows.tex').write_text('\n'.join(baseline)+'\n')
 import matplotlib
 matplotlib.use('Agg')
 matplotlib.rcParams['pdf.fonttype']=42
 matplotlib.rcParams['ps.fonttype']=42
 import matplotlib.pyplot as plt
 # No explicit colors: use the standard plotting palette; vector PDF/SVG output.
 selected=[('Pre-policy default','boto_false_default'),('2026 default','boto_true_default'),
           ('Pre-policy standard','boto_false_explicit_standard'),('2026 standard','boto_true_explicit_standard')]
 fig,ax=plt.subplots(figsize=(3.45,2.45))
 for i,(name,id) in enumerate(selected):
  values=[r['elapsed_s'] for r in groups[id]]
  ax.scatter(values,[i]*len(values),s=13,alpha=.75)
  ax.plot([statistics.median(values)],[i],marker='|',markersize=13)
 ax.set_xscale('log')
 ax.set_yticks(range(len(selected)),[name for name,id in selected]);ax.set_xlabel('Operation elapsed time (s)');ax.grid(axis='x',alpha=.2)
 fig.tight_layout();fig.savefig(out/'policy-time.pdf');fig.savefig(out/'policy-time.svg');plt.close(fig)
 # Timeline of a representative real run; observations, not an invented diagram.
 fig,ax=plt.subplots(figsize=(3.45,2.4))
 pairs=[('Boto headers','boto_trickle_headers_only'),('Requests body','req_native_trickle'),('Future wrapper','req_future_timeout_trickle')]
 for i,(name,id) in enumerate(pairs):
  r=next(r for r in groups[id] if r['seed']==101)
  ax.plot([0,r['elapsed_s']*1000],[i,i],linewidth=3,label='Operation interval' if i==0 else None)
  times=[(e['t']-r['start_t'])*1000 for e in r['events'] if e['kind']=='body_chunk']
  ax.scatter(times,[i]*len(times),s=9,marker='o')
  if 'timeout_signal_s' in r:ax.scatter([r['timeout_signal_s']*1000],[i],s=45,marker='x')
 ax.axvline(100,linestyle='--',linewidth=1,label='Requested budget')
 ax.set_yticks(range(len(pairs)),[n for n,id in pairs]);ax.set_xlabel('Milliseconds from operation entry');ax.grid(axis='x',alpha=.2)
 fig.tight_layout();fig.savefig(out/'boundary-time.pdf');fig.savefig(out/'boundary-time.svg');plt.close(fig)
 macros={'EvalRuns':len(rs),'EvalCells':len(groups),'EvalWires':summary['wire_attempts'],'EvalMaxWires':summary['maximum_wire_attempts'],
  'MismatchRuns':summary['verdicts'].get('mismatch',0),'UnknownRuns':summary['verdicts'].get('unknown',0),'SuccessControls':len(controls),
  'BotoControls':len(declared_boto),'OperationSeconds':f"{summary['operation_machine_seconds']:.1f}",
  'CheckMillis':f"{statistics.median(check_times):.1f}"}
 (out/'results-macros.tex').write_text('\n'.join('\\newcommand{\\'+k+'}{'+str(v)+'}' for k,v in macros.items())+'\n')
 if args.paper_dir:
  import shutil
  (args.paper_dir/'generated').mkdir(parents=True,exist_ok=True)
  (args.paper_dir/'figures').mkdir(parents=True,exist_ok=True)
  for p in out.glob('*.tex'):shutil.copy2(p,args.paper_dir/'generated'/p.name)
  for p in out.glob('*.pdf'):shutil.copy2(p,args.paper_dir/'figures'/p.name)
  for p in out.glob('*.svg'):shutil.copy2(p,args.paper_dir/'figures'/p.name)
 print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
