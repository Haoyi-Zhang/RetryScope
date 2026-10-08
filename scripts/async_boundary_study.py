#!/usr/bin/env python3
"""Actual cooperative timeout baseline, with return and cleanup observations."""
from pathlib import Path
import sys,asyncio,json,time,random,argparse,hashlib,datetime,platform
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from retryscope.responder import Reply,Responder
from retryscope.audit import AuditIntent,audit
import httpx

def cases():return [dict(id=f'{m}_{sc}_{scale}',mode=m,scenario=sc,scale=scale) for m in ('inactivity','admission','asyncio_timeout') for sc in ('success','trickle','slow_headers','retry_delay') for scale in (1,1.5)]
async def operation(c,server):
    k=c['scale'];budget=.1*k;arrivals=[];heads=[];attempt=0;stream_exits=[]
    setup=time.monotonic();client=httpx.AsyncClient(trust_env=False,timeout=httpx.Timeout(.08*k,connect=.1*k),transport=httpx.AsyncHTTPTransport(retries=0))
    r=dict(case=c,id=c['id'],httpx_version=httpx.__version__,setup_s=time.monotonic()-setup,budget_s=budget)
    async with client:
        start=time.monotonic()
        async def run():
            nonlocal attempt
            for _ in range(2):
                attempt+=1;arrivals.append(time.monotonic()-start)
                try:
                    async with client.stream('GET',server.url+'/body') as response:
                        heads.append(dict(t=time.monotonic()-start,status=response.status_code))
                        response.raise_for_status();body=await response.aread()
                        return body
                except httpx.HTTPStatusError as e:
                    if e.response.status_code!=503 or attempt==2:raise
                    delay=.18*k
                    if c['mode']=='admission' and time.monotonic()-start+delay>budget:
                        raise TimeoutError('next attempt refused before sleep') from e
                    await asyncio.sleep(delay)
                finally:
                    stream_exits.append(time.monotonic()-start)
            raise RuntimeError('unreachable loop exit')
        try:
            if c['mode']=='asyncio_timeout':
                async with asyncio.timeout(budget):body=await run()
            else:body=await run()
            r.update(outcome='success',payload=body.decode(),payload_complete=True)
        except Exception as e:r.update(outcome='error',exception=type(e).__name__,error=str(e)[:150],payload_complete=False)
        r.update(body_elapsed_s=time.monotonic()-start,body_complete=True,admissions_s=arrivals,admissions_complete=True,response_observations=heads,stream_exits_s=stream_exits)
    r.update(cleanup_elapsed_s=time.monotonic()-start,cleanup_complete=client.is_closed,client_closed=client.is_closed)
    r['expected_body_outcome']='success' if c['scenario']=='success' or c['scenario'] in ('trickle','retry_delay') and c['mode']=='inactivity' or c['scenario']=='trickle' and c['mode']=='admission' else 'error'
    complete=server.quiesce();r.update(arrival_stream_complete=complete and not server.cap_exceeded,wire_attempts=server.count,events=server.events,server_quiesced=complete)
    r['arrivals']=[dict(id=e['index'],t=e['t']) for e in server.events if e['kind']=='arrival']
    for b in ('body','cleanup'):
        r[b+'_audit']=audit(r,AuditIntent(budget_s=budget,boundary=b,provenance='explicit local elapsed-time probe; normal scheduling only'))
    return r

def main():
    a=argparse.ArgumentParser();a.add_argument('--out',type=Path,required=True);a.add_argument('--smoke',action='store_true');x=a.parse_args();x.out.mkdir(parents=True,exist_ok=False)
    jobs=cases();seeds=[600] if x.smoke else list(range(601,607))
    if x.smoke:jobs=[c for c in jobs if c['scenario']=='trickle' and c['scale']==1]
    src=[Path(__file__),ROOT/'study/async-boundary-protocol.md',ROOT/'src/retryscope/responder.py',ROOT/'src/retryscope/audit.py']
    freeze=dict(utc=datetime.datetime.now(datetime.UTC).isoformat(),python=platform.python_version(),httpx=httpx.__version__,cases=jobs,seeds=seeds,sources={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in src})
    (x.out/'freeze.json').write_text(json.dumps(freeze,indent=2)+'\n')
    with (x.out/'records.jsonl').open('x') as f:
        for seed in seeds:
            order=jobs[:];random.Random(seed).shuffle(order)
            for c in order:
                k=c['scale'];sc=c['scenario'];replies=[Reply(chunk_delay=.03*k)] if sc=='trickle' else [Reply(header_delay=.18*k)] if sc=='slow_headers' else [Reply(status=503),Reply()] if sc=='retry_delay' else [Reply()]
                with Responder(replies) as server:r=asyncio.run(operation(c,server))
                r['seed']=seed;f.write(json.dumps(r,allow_nan=False)+'\n');f.flush()
            print('completed',seed,flush=True)
if __name__=='__main__':main()
