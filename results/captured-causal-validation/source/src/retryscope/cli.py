"""Offline JSON trace audit. Exit codes: pass=0, mismatch=1, unknown=2, bad input=3."""
from __future__ import annotations
import argparse,json,sys,math
from pathlib import Path
from dataclasses import fields
from typing import Any
from .audit import audit,AuditIntent
from .migration import compare_migration

def strict_load(path: Path) -> Any:
    if path.stat().st_size>16*1024*1024:raise ValueError('JSON input exceeds 16 MiB')
    def pairs(xs):
        out={}
        for k,v in xs:
            if k in out:raise ValueError('duplicate JSON field: '+k)
            out[k]=v
        return out
    def bad_constant(s):raise ValueError('non-finite JSON number: '+s)
    return json.loads(path.read_text(encoding='utf8'),object_pairs_hook=pairs,parse_constant=bad_constant)

def validate_trace(r):
    if not isinstance(r,dict):raise ValueError('trace must be a JSON object')
    for flag in ['arrival_stream_complete','retry_attribution_complete','payload_complete','body_complete','headers_complete','cleanup_complete','admissions_complete']:
        if flag in r and type(r[flag]) is not bool:raise ValueError(flag+' must be boolean')
    if 'arrivals' in r:
        if not isinstance(r['arrivals'],list):raise ValueError('arrivals must be an array')
        for row in r['arrivals']:
            if not isinstance(row,dict):raise ValueError('arrival must be an object')
            if 'cause' in row and not isinstance(row['cause'],dict):raise ValueError('cause must be an object')
            if 'retry_of' in row and type(row['retry_of']) is not int:raise ValueError('retry_of must be an integer')
            if 'role' in row and row['role'] not in ('initial','constituent','retry','recovery','unknown'):raise ValueError('invalid request role')
    for key in ['body_elapsed_s','headers_elapsed_s','cleanup_elapsed_s']:
        if key in r and r[key] is not None and (type(r[key]) not in (int,float) or not math.isfinite(r[key]) or r[key]<0):raise ValueError('invalid '+key)
    return r

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--trace',type=Path,required=True);p.add_argument('--intent',type=Path,required=True);p.add_argument('--before',type=Path);p.add_argument('--output',type=Path)
    a=p.parse_args(argv)
    try:
        d=strict_load(a.intent)
        if not isinstance(d,dict):raise ValueError('intent must be an object')
        unknown=set(d)-{f.name for f in fields(AuditIntent)}
        if unknown:raise ValueError('unknown intent fields: '+', '.join(sorted(unknown)))
        intent=AuditIntent(**d);r=validate_trace(strict_load(a.trace))
        if a.before:
            before=validate_trace(strict_load(a.before))
            result=compare_migration(before,r,intent)
            result['verdict']=result['after']['verdict']
        else:
            result=audit(r,intent)
        text=json.dumps(result,indent=2,allow_nan=False)+'\n'
        if a.output:a.output.write_text(text)
        else:sys.stdout.write(text)
        return {'pass':0,'mismatch':1,'unknown':2}[result['verdict']]
    except (OSError,ValueError,TypeError,KeyError) as e:
        sys.stderr.write('Invalid audit input: '+str(e)+'\n');return 3
if __name__=='__main__':raise SystemExit(main())
