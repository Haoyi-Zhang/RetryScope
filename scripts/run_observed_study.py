#!/usr/bin/env python3
"""Run the evidence-complete initial matrix in fresh policy processes."""
from __future__ import annotations
import argparse, datetime, hashlib, json, os, subprocess, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main() -> None:
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=ROOT/'results/replay/observed')
    p.add_argument('--seeds',default=','.join(map(str,range(301,313))))
    p.add_argument('--ids',default='')
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    tracked=[ROOT/'study/cases.json',ROOT/'src/retryscope/observed_worker.py',ROOT/'src/retryscope/observation.py',ROOT/'src/retryscope/audit.py',ROOT/'src/retryscope/responder.py']
    freeze={'utc':datetime.datetime.now(datetime.UTC).isoformat(),'phase':'observed','seeds':a.seeds,'ids':a.ids,
            'files':{str(x.relative_to(ROOT)):sha(x) for x in tracked}}
    (a.out/'freeze.json').write_text(json.dumps(freeze,indent=2)+'\n')
    for flag in ('false','true'):
        target=a.out/f'{flag}.jsonl'
        cmd=[sys.executable,'-m','retryscope.observed_worker','--config',str(ROOT/'study/cases.json'),'--output',str(target),'--phase','observed','--seeds',a.seeds,'--flag',flag]
        if a.ids:cmd += ['--ids',a.ids]
        env=dict(os.environ);env['PYTHONPATH']=str(ROOT/'src')
        subprocess.run(cmd,cwd=ROOT,env=env,check=True)
    print(json.dumps(freeze,indent=2))
if __name__=='__main__':main()
