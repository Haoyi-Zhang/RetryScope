#!/usr/bin/env python3
"""Recompute follow-up summaries without pooling them with the main study."""
from pathlib import Path
import json,collections,statistics,csv,argparse
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser();p.add_argument('--raw-dir',type=Path,default=ROOT/'results/raw');p.add_argument('--output-dir',type=Path,default=ROOT/'results/derived');a=p.parse_args();a.output_dir.mkdir(parents=True,exist_ok=True)
 output={}
 for name,files,n in [('sensitivity',['sensitivity/true.jsonl'],80),('challenge',['challenge/records.jsonl'],112),('import-state',['import-state/records.jsonl'],3)]:
  rows=[json.loads(line) for file in files for line in (a.raw_dir/file).read_text().splitlines()]
  assert len(rows)==n,(name,len(rows));assert all(r['trace_complete'] and not r['cap_exceeded'] and r['wire_attempts']<=16 for r in rows)
  g=collections.defaultdict(list)
  for r in rows:g[r['id']].append(r)
  cells=[]
  for key,rs in sorted(g.items()):
   t=[r['elapsed_s']*1000 for r in rs]
   cells.append(dict(id=key,n=len(rs),pass_count=sum(r['check']['verdict']=='pass' for r in rs),mismatch_count=sum(r['check']['verdict']=='mismatch' for r in rs),success_count=sum(r.get('outcome')=='success' for r in rs),wire_min=min(r['wire_attempts'] for r in rs),wire_max=max(r['wire_attempts'] for r in rs),min_ms=min(t),median_ms=statistics.median(t),max_ms=max(t)))
  output[name]={'records':len(rows),'wire_attempts':sum(r['wire_attempts'] for r in rows),'verdicts':dict(collections.Counter(r['check']['verdict'] for r in rows)),'cells':cells}
  with (a.output_dir/f'{name}-summary.csv').open('w') as f:
   w=csv.DictWriter(f,fieldnames=list(cells[0]));w.writeheader();w.writerows(cells)
 (a.output_dir/'followups.json').write_text(json.dumps(output,indent=2)+'\n')
 print({k:{x:v[x] for x in ('records','wire_attempts','verdicts')} for k,v in output.items()})
if __name__=='__main__':main()
