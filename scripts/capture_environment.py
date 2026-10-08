#!/usr/bin/env python3
"""Preserve actual source evidence and licenses, not whole unrelated environments."""
from pathlib import Path
import importlib,importlib.metadata as md,platform,sys,os,json,hashlib,shutil
ROOT=Path(__file__).resolve().parents[1]
MODULES={
 'botocore.configprovider':'botocore','botocore.retries.standard':'botocore','botocore.args':'botocore','botocore.response':'botocore',
 'requests.models':'requests','requests.adapters':'requests','urllib3.response':'urllib3','urllib3.util.timeout':'urllib3','urllib3.util.retry':'urllib3',
 'pip._vendor.urllib3.response':'pip','pip._vendor.requests.models':'pip','smart_open.s3':'smart_open',
 'huggingface_hub.utils._http':'huggingface_hub','huggingface_hub.hf_api':'huggingface_hub','retrying':'retrying'}
def main():
 out=ROOT/'evidence/source-snapshots';out.mkdir(parents=True,exist_ok=True)
 records=[]
 for module,dist in MODULES.items():
  m=importlib.import_module(module);p=Path(m.__file__)
  target=out/(module.replace('.','_')+'.py');shutil.copy2(p,target)
  records.append(dict(module=module,distribution=dist,version=md.version(dist),sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
     snapshot=str(target.relative_to(ROOT)),installed_origin=str(p),bytes=p.stat().st_size))
 for dist in sorted(set(MODULES.values())):
  d=md.distribution(dist);base=out/'licenses'/dist;base.mkdir(parents=True,exist_ok=True)
  (base/'METADATA.txt').write_text(d.read_text('METADATA') or '')
  for f in d.files or []:
   if any(s in str(f).upper() for s in ('LICENSE','COPYING','NOTICE')) and str(f).lower().endswith(('.txt','.md','.rst','license','copying','notice')):
    p=Path(d.locate_file(f))
    if p.is_file() and p.stat().st_size<200000:shutil.copy2(p,base/str(f).replace('/','_'))
 manifest=dict(python=sys.version,platform=platform.platform(),cpu_available=os.cpu_count(),source_files=records,
   packages={p:md.version(p) for p in ['boto3','botocore','s3transfer','requests','urllib3','httpx','httpcore','retrying','smart_open','huggingface_hub','pip','pytest','numpy','matplotlib']},
   environment_names_only=[k for k in os.environ if k.startswith(('AWS_','HF_'))])
 (ROOT/'evidence/environment.json').write_text(json.dumps(manifest,indent=2)+'\n')
 print('Captured',len(records),'actual source files and distribution licenses')
if __name__=='__main__':main()
