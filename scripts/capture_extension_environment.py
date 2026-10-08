#!/usr/bin/env python3
"""Capture installed extension inputs, source snapshots, and distribution licenses."""
from __future__ import annotations
import hashlib, importlib, importlib.metadata as md, json, platform, shutil
from pathlib import Path
from packaging.requirements import Requirement
ROOT=Path(__file__).resolve().parents[1]
def main():
    target=ROOT/'evidence/extension-source';target.mkdir(parents=True,exist_ok=True)
    mods=['pooch.core','pooch.downloaders','pooch.utils','fsspec.implementations.http','fsspec.caching','aiohttp.client','aiohttp.client_reqrep','httpx._client','httpx._config']
    result={'python':platform.python_version(),'platform':platform.platform(),'modules':[],'licenses':[],'packages':{}}
    for name in mods:
        source=Path(importlib.import_module(name).__file__);out=target/(name.replace('.','__')+'.py');shutil.copy2(source,out)
        result['modules'].append(dict(module=name,source_name=source.name,snapshot=str(out.relative_to(ROOT)),sha256=hashlib.sha256(out.read_bytes()).hexdigest()))
    todo=['pooch','aiohttp','fsspec','httpx'];seen=set()
    while todo:
        name=todo.pop();dist=md.distribution(name);canonical=dist.metadata['Name']
        norm=canonical.lower().replace('_','-')
        if norm in seen:continue
        seen.add(norm);result['packages'][canonical]=dist.version
        for text in dist.requires or []:
            req=Requirement(text)
            if req.marker is None or req.marker.evaluate({'extra':''}):todo.append(req.name)
    for name in ('pooch','aiohttp','fsspec','httpx'):
        dist=md.distribution(name);ld=target/'licenses'/name;ld.mkdir(parents=True,exist_ok=True)
        (ld/'METADATA').write_text(dist.read_text('METADATA') or '')
        for f in dist.files or []:
            if 'licenses/' not in str(f):continue
            src=dist.locate_file(f)
            if not src.is_file():continue
            relative=str(f).split('licenses/',1)[1];out=ld/relative;out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,out)
            result['licenses'].append(dict(package=name,path=str(out.relative_to(ROOT)),sha256=hashlib.sha256(out.read_bytes()).hexdigest()))
    old={line.split('==')[0].lower().replace('_','-') for line in (ROOT/'requirements/locked.txt').read_text().splitlines() if '==' in line}
    additions=sorted((n,v) for n,v in result['packages'].items() if n.lower().replace('_','-') not in old)
    (ROOT/'requirements/extension.txt').write_text('# Base pins plus exact extension dependencies actually installed.\n-r locked.txt\n'+''.join(f'{n}=={v}\n' for n,v in additions))
    (ROOT/'evidence/extension-environment.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(packages=result['packages'],source_snapshots=len(result['modules']),licenses=len(result['licenses'])),indent=2))
if __name__=='__main__':main()
