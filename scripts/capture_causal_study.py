"""Execute a new loopback campaign from captured source, never relabel an old run."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def source_files(root: Path) -> list[Path]:
    return [root/'scripts/causal_witness_study.py', root/'scripts/capture_causal_study.py',
            *sorted((root/'src/retryscope').glob('*.py'))]


def capture_sources(root: Path, destination: Path) -> dict[str, str]:
    identities = {}
    for source in source_files(root):
        relative = source.relative_to(root)
        target = destination/relative
        payload = source.read_bytes()
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(payload)
        identities[relative.as_posix()] = hashlib.sha256(payload).hexdigest()
    return identities


def verify_capture(snapshot: Path, expected: dict[str, str]) -> None:
    for relative, digest in expected.items():
        if hashlib.sha256((snapshot/relative).read_bytes()).hexdigest() != digest:
            raise ValueError('Captured source changed: '+relative)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path,
                        help='new campaign directory; an existing directory is never overwritten')
    parser.add_argument('--timeout-seconds', type=int, default=240)
    parser.add_argument('--stacks', default='requests,urllib3')
    parser.add_argument('--scenarios', default='retry,nested,constituent,recovery')
    parser.add_argument('--concurrency', default='1,2,4,8')
    parser.add_argument('--seeds', default='11,23,37,53,71,89')
    args=parser.parse_args()
    if args.timeout_seconds < 1:
        parser.error('timeout must be positive')
    output=args.output.resolve()
    output.mkdir(parents=True,exist_ok=False)
    snapshot=output/'source'
    identities=capture_sources(ROOT,snapshot)
    verify_capture(snapshot,identities)
    raw=output/'raw.jsonl'
    command=[sys.executable,'-B','-u',str(snapshot/'scripts/causal_witness_study.py'),
             '--output',str(raw),'--stacks',args.stacks,'--scenarios',args.scenarios,
             '--concurrency',args.concurrency,'--seeds',args.seeds]
    manifest=dict(status='started',started_utc=datetime.now(timezone.utc).isoformat(),
                  environment=dict(python=platform.python_version(),implementation=platform.python_implementation(),
                                   system=platform.system(),release=platform.release(),machine=platform.machine(),
                                   processor=platform.processor(),logical_cpus=os.cpu_count(),
                                   dependencies={p:importlib.metadata.version(p) for p in ('requests','urllib3')}),
                  sources=identities,executed_from_captured_tree=True,
                  parameters={k:getattr(args,k) for k in ('stacks','scenarios','concurrency','seeds')},
                  timeout_seconds=args.timeout_seconds,
                  historical_run_reconstructed=False)
    record=output/'execution.json'
    record.write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    env={**os.environ,'PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1',
         'PYTHONPATH':os.pathsep.join([str(snapshot/'src'),os.environ.get('PYTHONPATH','')])}
    start=time.perf_counter()
    with (output/'stdout.txt').open('w',encoding='utf-8') as stdout, \
         (output/'stderr.txt').open('w',encoding='utf-8') as stderr:
        try:
            process=subprocess.run(command,cwd=snapshot,env=env,stdout=stdout,stderr=stderr,
                                   timeout=args.timeout_seconds,check=False)
            manifest['returncode']=process.returncode
            manifest['status']='passed' if process.returncode==0 else 'failed'
        except subprocess.TimeoutExpired:
            manifest.update(status='timeout',returncode=None)
    manifest.update(finished_utc=datetime.now(timezone.utc).isoformat(),wall_seconds=time.perf_counter()-start)
    verify_capture(snapshot,identities)
    if raw.exists():
        manifest['raw_sha256']=hashlib.sha256(raw.read_bytes()).hexdigest()
        rows=[json.loads(line) for line in raw.read_text(encoding='utf-8').splitlines()]
        manifest['batches']=len(rows)
        manifest['operations']=sum(len(row['operations']) for row in rows)
        manifest['wire_requests']=sum(len(row['wire_events']) for row in rows)
    record.write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:manifest[k] for k in ('status','executed_from_captured_tree','historical_run_reconstructed',
                                            'batches','operations','wire_requests') if k in manifest}))
    return 0 if manifest['status']=='passed' else 1


if __name__=='__main__':
    raise SystemExit(main())
