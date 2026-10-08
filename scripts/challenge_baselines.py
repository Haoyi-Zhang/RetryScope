#!/usr/bin/env python3
"""Post-evaluation ordinary-baseline challenge and public-API causal ablation.

No old package is patched. Requests/urllib3 are imported from actual installed
versions. Only public adapter/response options change. Outputs are immutable.
"""
import sys, time, json, random, argparse, hashlib, datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from retryscope.responder import Responder, Reply
from retryscope.checker import Intent, check
from retryscope.ordinary import checked_identity_body
from retrying import Retrying

def main():
    p=argparse.ArgumentParser();p.add_argument('--output-dir',type=Path,default=ROOT/'results/raw/challenge');a=p.parse_args()
    a.output_dir.mkdir(parents=True,exist_ok=True)
    freeze={'utc':datetime.datetime.now(datetime.UTC).isoformat(),'phase':'post-evaluation-baseline-challenge','seeds':list(range(201,209)),
      'sources':{str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in [Path(__file__),ROOT/'src/retryscope/ordinary.py']},
      'plan':'2 stacks x 5 scenarios x 8 repeats; public enforce_content_length 2 stacks x 2 options x 8 repeats. Do not combine with main evaluation.'}
    with (a.output_dir/'freeze.json').open('x') as f:json.dump(freeze,f,indent=2)
    scripts={'success':[Reply()], 'transient':[Reply(status=503),Reply()], 'persistent':[Reply(status=503)],'denied':[Reply(status=400)],'truncated':[Reply(truncate=True),Reply()]}
    jobs=[('ordinary',old,scenario,None) for old in [False,True] for scenario in scripts]+[('ablation',old,'truncated',enforce) for old in [False,True] for enforce in [False,True]]
    with (a.output_dir/'records.jsonl').open('x') as f:
      for seed in range(201,209):
       order=list(jobs);random.Random(seed).shuffle(order)
       for phase,old,scenario,enforce in order:
        if old:
            from pip._vendor import requests, urllib3
        else:
            import requests, urllib3
        with Responder(scripts[scenario]) as server:
            name=f'{phase}_{"old" if old else "new"}_{scenario}'+('' if enforce is None else f'_{enforce}')
            record={'id':name,'phase':phase,'seed':seed,'request_version':requests.__version__,'urllib3_version':urllib3.__version__,'enforce_content_length':enforce,'read_timeout_s':.08}
            session=requests.Session();session.trust_env=False
            # Disable inner retries; own the total operation at exactly one layer.
            session.mount('http://',requests.adapters.HTTPAdapter(max_retries=0))
            pool=urllib3.PoolManager(retries=False,timeout=urllib3.util.Timeout(connect=.1,read=.08))
            start=time.monotonic();record['start_t']=start
            try:
                if phase=='ordinary':
                    def one():
                        with session.get(server.url+'/data',timeout=(.1,.08)) as r:
                            return checked_identity_body(r,requests.exceptions.ChunkedEncodingError)
                    def eligible(e):
                        return isinstance(e,(requests.exceptions.Timeout,requests.exceptions.ConnectionError,requests.exceptions.ChunkedEncodingError)) or (isinstance(e,requests.exceptions.HTTPError) and e.response is not None and e.response.status_code==503)
                    body=Retrying(stop_max_attempt_number=2,wait_fixed=20,retry_on_exception=eligible).call(one)
                else:
                    r=pool.request('GET',server.url+'/data',preload_content=False,enforce_content_length=enforce)
                    chunks=[]
                    try:
                        while True:
                            piece=r.read(4)
                            if not piece:break
                            chunks.append(piece)
                    finally:r.close()
                    body=b''.join(chunks)
                record.update(outcome='success',payload=body.decode('ascii'))
            except Exception as e:record.update(outcome='error',exception=type(e).__name__,error_message=str(e)[:200])
            finally:session.close();pool.clear()
            record['elapsed_s']=time.monotonic()-start
            record.update(trace_complete=server.quiesce() and not server.cap_exceeded,wire_attempts=server.count,events=server.events,cap_exceeded=server.cap_exceeded)
        intent=Intent(max_wire_attempts=2 if phase=='ordinary' else 1,retryable_statuses=(503,),allow_body_recovery=True,expected_payload_on_success='0123456789',required_outcome=('success' if scenario in ('success','transient','truncated') else 'error') if phase=='ordinary' else None,provenance='post-evaluation researcher-authored application contract')
        record['intent']=intent.to_dict();record['check']=check(record,intent)
        f.write(json.dumps(record,sort_keys=True)+'\n');f.flush()
    print('Completed 80 ordinary-baseline and 32 public-API ablation operations.')
if __name__=='__main__':main()
