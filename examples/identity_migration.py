#!/usr/bin/env python3
"""Executed before/after identity check; loopback only, new directory required."""
from pathlib import Path
import argparse, hashlib, json, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'));sys.path.insert(0,str(ROOT/'src'))
from extend_study import run,matrix,PAYLOAD
from retryscope.audit import AuditIntent,audit
from retryscope.migration import compare_migration

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True,type=Path);a=p.parse_args()
    a.out.mkdir(parents=True,exist_ok=False)
    rows={c['id']:c for c in matrix()}
    intent=AuditIntent(expected_payload=PAYLOAD.decode(),provenance='explicit known-object download requirement')
    rs={label:run(rows[key],701) for label,key in [('before','requests_old_length_corrupt_once'),('after','requests_old_hash_corrupt_once')]}
    for label,r in rs.items():(a.out/(label+'.json')).write_text(json.dumps(r,indent=2)+'\n')
    (a.out/'intent.json').write_text(json.dumps(intent.to_dict(),indent=2)+'\n')
    result={label:dict(verdict=audit(r,intent)['verdict'],outcome=r['outcome'],requests=r['wire_attempts'],matches_expected=r['payload']==PAYLOAD.decode(),elapsed_s=r['body_elapsed_s']) for label,r in rs.items()}
    result['comparison']=compare_migration(rs['before'],rs['after'],intent,pair_id='identity_migration_example')
    result['example_source_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    assert result['before']['verdict']=='mismatch' and result['before']['requests']==1
    assert result['after']['verdict']=='pass' and result['after']['requests']==2
    assert result['comparison']['category']=='repair'
    (a.out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
