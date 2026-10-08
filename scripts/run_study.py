#!/usr/bin/env python3
"""Fresh processes isolate import-time policy; raw files are never overwritten."""
from pathlib import Path
import argparse, subprocess, sys, os, hashlib, json, datetime
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser()
 p.add_argument('--phase',choices=['pilot','evaluation','sensitivity','smoke'],default='evaluation')
 p.add_argument('--output-dir',type=Path)
 a=p.parse_args()
 out=a.output_dir or ROOT/'results'/'raw'/a.phase
 out.mkdir(parents=True,exist_ok=True)
 config=ROOT/'study'/'cases.json'
 seeds={'pilot':'11','evaluation':','.join(map(str,range(101,113))),'sensitivity':','.join(map(str,range(201,209))),'smoke':'301'}[a.phase]
 if a.phase=='sensitivity':
  cases=json.loads(config.read_text())
  cases=[c for c in cases if c['scenario']=='trickle' and c['mode']!='headers_only']
  for c in cases:
   c['scale']=1.5;c['read_timeout']=.12
   c['intent']['budget_s']=.15;c['budget']=.15
  config=out/'sensitivity-cases.json';config.write_text(json.dumps(cases,indent=2)+'\n')
 freeze={'utc':datetime.datetime.now(datetime.UTC).isoformat(),'phase':a.phase,'seeds':seeds,
   'files':{str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted((ROOT/'src').rglob('*.py'))}}
 freeze['cases_sha256']=hashlib.sha256(config.read_bytes()).hexdigest()
 freeze_path=out/'freeze.json'
 if freeze_path.exists(): raise SystemExit('Output exists; choose a fresh --output-dir')
 freeze_path.write_text(json.dumps(freeze,indent=2)+'\n')
 env=dict(os.environ,PYTHONPATH=str(ROOT/'src'),PYTHONUNBUFFERED='1')
 for flag in ['false','true']:
  cmd=[sys.executable,'-m','retryscope.worker','--config',str(config),'--output',str(out/f'{flag}.jsonl'),'--phase',a.phase,'--seeds',seeds,'--flag',flag]
  if a.phase=='smoke': cmd+=['--ids','boto_true_total2,req_normalized_persistent,smart_truncated,urllib3_old_truncated,urllib3_new_truncated,hf_normalized_transient']
  with (out/f'{flag}.log').open('w') as log:
   subprocess.run(cmd,check=True,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=900)
  print(f'Completed {a.phase}, flag={flag}',flush=True)
if __name__=='__main__':main()
