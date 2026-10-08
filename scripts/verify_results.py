#!/usr/bin/env python3
"""Check frozen implementation identity and all reported raw records offline.

This is a reproducibility self-check, not independent peer review.
"""
from pathlib import Path
import json, hashlib, sys, collections, argparse
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from retryscope.checker import Intent, check

def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def records(folder):
    return [json.loads(line) for p in sorted(folder.glob('*.jsonl')) for line in p.read_text().splitlines() if line.strip()]
def frozen_source(relative, expected):
    current=ROOT/relative
    if current.is_file() and digest(current)==expected:
        return current
    mapping=json.loads((ROOT/'evidence/FROZEN-SOURCE-MAP.json').read_text())
    matches=[entry for entry in mapping['relocations'] if entry['frozen_path']==relative and entry['sha256']==expected]
    assert len(matches)==1, ('no unique frozen source relocation',relative,expected)
    preserved=ROOT/matches[0]['preserved_path']
    assert digest(preserved)==expected, ('frozen source digest mismatch',relative)
    return preserved

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path);a=p.parse_args()
    freeze=json.loads((ROOT/'results/raw/evaluation/freeze.json').read_text())
    for rel,sha in freeze['files'].items():
        frozen_source(rel,sha)
    assert digest(ROOT/'study/cases.json')==freeze['cases_sha256']
    challenge=json.loads((ROOT/'results/raw/challenge/freeze.json').read_text())
    for rel,sha in challenge['sources'].items():
        frozen_source(rel,sha)
    evidence=json.loads((ROOT/'evidence/environment.json').read_text())
    for entry in evidence['source_files']:
        assert digest(ROOT/entry['snapshot'])==entry['sha256'],entry['snapshot']
    expected={'evaluation':1068,'sensitivity':80,'challenge':112,'import-state':3}
    report={}
    for phase,n in expected.items():
        rr=records(ROOT/'results/raw'/phase)
        assert len(rr)==n,(phase,len(rr))
        assert len({(r['id'],r['seed']) for r in rr})==n,('duplicate',phase)
        for r in rr:
            assert r['trace_complete'] and not r.get('harness_error'),r['id']
            assert 0 < r['wire_attempts'] <=16,r['id']
            assert r['wire_attempts']==sum(e['kind']=='arrival' for e in r['events'])
            assert r['check']==check(r,Intent(**(r['intent'] if 'intent' in r else r['config']['intent']))),r['id']
        report[phase]={'records':n,'wire_attempts':sum(r['wire_attempts'] for r in rr),
            'verdicts':dict(collections.Counter(r['check']['verdict'] for r in rr))}
    assert report['evaluation']['verdicts']=={'pass':756,'mismatch':300,'unknown':12}
    assert report['evaluation']['wire_attempts']==1704
    assert report['challenge']['verdicts']=={'pass':96,'mismatch':16}
    result={'self_check':'passed','frozen_main_sources_match':True,
            'source_snapshots_verified':len(evidence['source_files']),'phases':report}
    text=json.dumps(result,indent=2)+'\n'
    if a.output: a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(text)
    print(text,end='')
if __name__=='__main__': main()
