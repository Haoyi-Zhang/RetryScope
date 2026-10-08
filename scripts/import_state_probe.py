#!/usr/bin/env python3
"""Three bounded process-isolated diagnostics of import-time opt-in state."""
from pathlib import Path
import os,sys,json,argparse,subprocess,datetime,hashlib
ROOT=Path(__file__).resolve().parents[1]
CHILD='''import os,json
from retryscope import worker
os.environ['AWS_NEW_RETRIES_2026']=os.environ['INITIAL_FLAG']
import botocore.configprovider
os.environ['AWS_NEW_RETRIES_2026']=os.environ['LATER_FLAG']
c={'id':'import_'+os.environ['INITIAL_FLAG']+'_to_'+os.environ['LATER_FLAG'],'stack':'boto','mode':'body','scenario':'persistent','intent':{}}
r=worker.run(c,303,'import-state-diagnostic')
r['initial_flag']=os.environ['INITIAL_FLAG']
print(json.dumps(r,sort_keys=True))
'''
def main():
 p=argparse.ArgumentParser();p.add_argument('--output-dir',type=Path,default=ROOT/'results/raw/import-state');a=p.parse_args()
 a.output_dir.mkdir(parents=True,exist_ok=True)
 with (a.output_dir/'freeze.json').open('x') as f:json.dump({'utc':datetime.datetime.now(datetime.UTC).isoformat(),'phase':'post-evaluation-import-probe','script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},f)
 with (a.output_dir/'records.jsonl').open('x') as f:
  for initial,later in [('false','true'),('true','false'),('true','true')]:
   env=dict(os.environ,PYTHONPATH=str(ROOT/'src'),INITIAL_FLAG=initial,LATER_FLAG=later)
   r=subprocess.run([sys.executable,'-c',CHILD],env=env,text=True,capture_output=True,timeout=35,check=True)
   row=json.loads(r.stdout);f.write(json.dumps(row,sort_keys=True)+'\n');f.flush()
   print(initial,later,row['effective_flag'],row['effective_retries'],row['wire_attempts'])
if __name__=='__main__':main()
