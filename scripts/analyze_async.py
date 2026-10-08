#!/usr/bin/env python3
"""Verify frozen real-clock async runs and regenerate their tables and vector plot."""
from __future__ import annotations
import argparse, collections, csv, hashlib, json, statistics, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from retryscope.audit import AuditIntent,audit

def main():
    p=argparse.ArgumentParser();p.add_argument('--raw',type=Path,default=ROOT/'results/raw/async-boundary');p.add_argument('--out',type=Path,default=ROOT/'results/async-derived');p.add_argument('--paper-dir',type=Path);a=p.parse_args()
    freeze=json.loads((a.raw/'freeze.json').read_text())
    frozen_relocations = {
        'src/retryscope/audit.py': ROOT/'evidence/source-snapshots/frozen-extension-audit.py',
        'study/async-boundary-protocol.md': ROOT/'evidence/source-snapshots/frozen-async-protocol.md',
    }
    for rel,d in freeze['sources'].items():
        source = ROOT/rel
        if hashlib.sha256(source.read_bytes()).hexdigest() != d and rel in frozen_relocations:
            source = frozen_relocations[rel]
        assert hashlib.sha256(source.read_bytes()).hexdigest()==d,rel
    rs=[json.loads(l) for l in (a.raw/'records.jsonl').read_text().splitlines() if l.strip()]
    expected={(c['id'],s) for c in freeze['cases'] for s in freeze['seeds']}
    assert len(rs)==len(expected) and {(r['id'],r['seed']) for r in rs}==expected
    for r in rs:
        assert r['outcome']==r['expected_body_outcome'],r['id']
        assert r['client_closed'] and r['server_quiesced'] and r['body_complete'] and r['cleanup_complete']
        assert 1<=r['wire_attempts']<=16 and r['wire_attempts']==len(r['arrivals'])
        assert r['wire_attempts']==sum(e['kind']=='arrival' for e in r['events'])
        assert r['cleanup_elapsed_s']>=r['body_elapsed_s']>=0
        for b in ('body','cleanup'):
            assert audit(r,AuditIntent(budget_s=r['budget_s'],boundary=b,provenance='explicit local elapsed-time probe; normal scheduling only'))==r[b+'_audit']
    a.out.mkdir(parents=True,exist_ok=True)
    rows=[]
    for case in freeze['cases']:
        sub=[r for r in rs if r['id']==case['id']];ts=[1000*r['cleanup_elapsed_s'] for r in sub]
        rows.append(dict(**case,n=len(sub),wire_min=min(r['wire_attempts'] for r in sub),wire_max=max(r['wire_attempts'] for r in sub),outcome=sub[0]['outcome'],budget_ms=sub[0]['budget_s']*1000,median_ms=statistics.median(ts),min_ms=min(ts),max_ms=max(ts),body_pass=sum(r['body_audit']['verdict']=='pass' for r in sub),cleanup_pass=sum(r['cleanup_audit']['verdict']=='pass' for r in sub)))
    with (a.out/'cells.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    summary=dict(records=len(rs),cells=len(freeze['cases']),seeds=freeze['seeds'],wire_attempts=sum(r['wire_attempts'] for r in rs),max_wire_attempts=max(r['wire_attempts'] for r in rs),expected_outcomes=sum(r['outcome']==r['expected_body_outcome'] for r in rs),clients_closed=sum(r['client_closed'] for r in rs),body_verdicts=dict(collections.Counter(r['body_audit']['verdict'] for r in rs)),cleanup_verdicts=dict(collections.Counter(r['cleanup_audit']['verdict'] for r in rs)),raw_sha256=hashlib.sha256((a.raw/'records.jsonl').read_bytes()).hexdigest())
    summary['modes']={m:dict(n=sum(r['case']['mode']==m for r in rs),cleanup_pass=sum(r['case']['mode']==m and r['cleanup_audit']['verdict']=='pass' for r in rs)) for m in ('inactivity','admission','asyncio_timeout')}
    (a.out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    byid={r['id']:r for r in rows};lines=[]
    for m,label in [('inactivity','Inactivity only'),('admission','Admission guard'),('asyncio_timeout',r'\code{asyncio.timeout}')]:
        for scale in (1,1.5):
            parts=[]
            for sc in ('success','trickle','slow_headers','retry_delay'):
                r=byid[f'{m}_{sc}_{scale}'];parts.append(f"{r['median_ms']:.1f} [{r['min_ms']:.1f}, {r['max_ms']:.1f}]")
            lines.append(label+f' & {100*scale:.0f} & '+' & '.join(parts)+r' \\')
    (a.out/'async-rows.tex').write_text('\n'.join(lines)+'\n')
    import matplotlib
    matplotlib.use('Agg');matplotlib.rcParams['pdf.fonttype']=42;matplotlib.rcParams['ps.fonttype']=42
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(3.48,2.30))
    for i,(m,label) in enumerate([('inactivity','Inactivity'),('admission','Admission'),('asyncio_timeout','Async context')]):
        rr=[byid[f'{m}_trickle_{s}'] for s in (1,1.5)]
        med=[r['median_ms'] for r in rr]
        ax.errorbar([r['budget_ms'] for r in rr],med,yerr=[[r['median_ms']-r['min_ms'] for r in rr],[r['max_ms']-r['median_ms'] for r in rr]],marker='o',capsize=3,label=label,linestyle=['-','--',':'][i])
    ax.plot([100,150],[120,170],label='Budget + 20 ms',linestyle='-.')
    ax.set_xticks([100,150]);ax.set_xlabel('Local operation budget (ms)');ax.set_ylabel('Through client close (ms)');ax.legend(frameon=False,fontsize=8,loc='center right');ax.grid(alpha=.15);fig.tight_layout()
    # Reject cropped axis labels before exporting the fixed-size vector figure.
    fig.canvas.draw()
    for text in (ax.xaxis.label, ax.yaxis.label):
        box=text.get_window_extent(fig.canvas.get_renderer())
        assert box.x0 >= 0 and box.y0 >= 0 and box.x1 <= fig.bbox.x1 and box.y1 <= fig.bbox.y1, text.get_text()
    # Keep the legend clear of measured curves and the budget reference.
    legend_box=ax.get_legend().get_window_extent(fig.canvas.get_renderer())
    for line in ax.lines:
        pts=line.get_xydata()
        if line.get_linestyle() not in ('None','none','') and len(pts)>1:
            import numpy as np
            pts=np.vstack([np.linspace(left,right,101) for left,right in zip(pts[:-1],pts[1:])])
        assert not any(legend_box.contains(*xy) for xy in line.get_transform().transform(pts)), 'legend obscures a plotted curve'
    for ext in ('pdf','svg'):fig.savefig(a.out/('async-cleanup.'+ext))
    plt.close(fig)
    if a.paper_dir:
        import shutil
        for d in ('generated','figures'):(a.paper_dir/d).mkdir(exist_ok=True,parents=True)
        shutil.copy2(a.out/'async-rows.tex',a.paper_dir/'generated/async-rows.tex')
        for ext in ('pdf','svg'):shutil.copy2(a.out/('async-cleanup.'+ext),a.paper_dir/'figures'/('async-cleanup.'+ext))
    print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
