#!/usr/bin/env python3
"""Resume absent cells after interrupted execution without replacing observations."""
from pathlib import Path
import argparse,datetime,json,random,signal
from extend_study import ROOT,run,sha

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--seed',type=int);a=p.parse_args()
    freeze=json.loads((a.out/'freeze.json').read_text())
    for rel,digest in freeze['sources'].items():
        if sha(ROOT/rel)!=digest:raise SystemExit('Frozen source mismatch: '+rel)
    data=a.out/'records.jsonl';records=[json.loads(l) for l in data.read_text().splitlines()]
    seen={(r['id'],r['seed']) for r in records}
    if len(seen)!=len(records):raise SystemExit('Duplicate records')
    log={'utc':datetime.datetime.now(datetime.UTC).isoformat(),'existing_records':len(records),'prefix_sha256':sha(data),'reason':'tool timeout; append only absent cells','runner_sha256':sha(Path(__file__))}
    with (a.out/'resume-log.jsonl').open('a') as f:f.write(json.dumps(log)+'\n')
    def timeout(*_):raise RuntimeError('bounded operation watchdog fired')
    signal.signal(signal.SIGALRM,timeout)
    with data.open('a') as out:
        for seed in freeze['seeds']:
            if a.seed is not None and seed!=a.seed:continue
            ordered=freeze['cases'][:];random.Random(seed).shuffle(ordered)
            for c in ordered:
                if (c['id'],seed) in seen:continue
                signal.setitimer(signal.ITIMER_REAL,25)
                try:r=run(c,seed)
                finally:signal.setitimer(signal.ITIMER_REAL,0)
                out.write(json.dumps(r,allow_nan=False)+'\n');out.flush()
                print(seed,c['id'],r['outcome'],r['wire_attempts'],flush=True)
if __name__=='__main__':main()
