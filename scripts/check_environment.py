#!/usr/bin/env python3
"""Fail clearly on material runtime drift; print no environment secrets."""
from pathlib import Path
import importlib.metadata as md
import json, sys, platform, argparse
ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--strict',action='store_true'); args=parser.parse_args()
    expected=json.loads((ROOT/'evidence/environment.json').read_text())['packages']
    mismatches=[]
    for name,version in expected.items():
        try: actual=md.version(name)
        except md.PackageNotFoundError: actual='NOT INSTALLED'
        if actual!=version: mismatches.append({'package':name,'expected':version,'actual':actual})
    runtime={'python':platform.python_version(),'platform':platform.system(),
             'executed_python':'3.13.5','executed_platform':'Linux', 'package_mismatches':mismatches}
    print(json.dumps(runtime,indent=2))
    if args.strict and (mismatches or platform.python_version()!='3.13.5' or platform.system()!='Linux'):
        raise SystemExit('Recorded execution environment differs. Do not label the replay an exact repeat.')
if __name__=='__main__':main()
